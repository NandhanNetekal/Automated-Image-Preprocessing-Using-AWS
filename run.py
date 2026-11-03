
import os
import uuid
from io import BytesIO

from flask import (
    Flask, render_template, request,
    redirect, url_for, flash
)

from werkzeug.utils import secure_filename
from PIL import Image
from dotenv import load_dotenv

from app.services.image_processor import process_image

from app.services.s3_service import (
    upload_image,
    list_images,
    generate_image_url,
    upload_processed_image,
    list_processed_images,
    generate_download_url,
    get_image_metadata,
    delete_image,
    s3_client,
    BUCKET_NAME
)

from app.services.db_service import (
    get_db_connection,
    save_image_metadata,
    save_processing_history
)


load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")

app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

ALLOWED_FORMATS = {
    "JPEG": ("jpg", "image/jpeg"),
    "PNG": ("png", "image/png")
}


# --------------------------------------------------
# HOME AND IMAGE UPLOAD
# --------------------------------------------------

@app.route("/", methods=["GET", "POST"])
def home():

    if request.method == "POST":

        if "image" not in request.files:
            flash("Please select an image.", "error")
            return redirect(url_for("home"))

        file = request.files["image"]

        if file.filename == "":
            flash("No image selected.", "error")
            return redirect(url_for("home"))

        try:
            image = Image.open(file.stream)
            image_format = image.format
            width, height = image.size

            if image_format not in ALLOWED_FORMATS:
                flash("Only JPG and PNG images are allowed.", "error")
                return redirect(url_for("home"))

            image.verify()

            extension, content_type = ALLOWED_FORMATS[image_format]
            original_name = secure_filename(file.filename)

            filename = f"{uuid.uuid4().hex}.{extension}"

            # Read image bytes
            file.stream.seek(0)
            image_bytes = file.stream.read()

            file_size = len(image_bytes)

            # Upload original image to AWS S3
            upload_image(
                BytesIO(image_bytes),
                filename,
                content_type
            )

            # Save image metadata in MySQL
            image_id = save_image_metadata(
                filename,
                f"uploads/{filename}",
                file_size,
                width,
                height
            )

            if image_id:
                flash(
                    f"{original_name} uploaded successfully to AWS S3 "
                    "and image details saved in MySQL!",
                    "success"
                )
            else:
                flash(
                    f"{original_name} uploaded to AWS S3, "
                    "but database metadata could not be saved.",
                    "warning"
                )

        except Exception:
            app.logger.exception("Image upload failed")
            flash(
                "Image upload failed. Please check the server logs.",
                "error"
            )

        return redirect(url_for("home"))

    images = [
        {
            "filename": key.split("/")[-1],
            "url": generate_image_url(key)
        }
        for key in list_images()
    ]

    return render_template("index.html", images=images)


# --------------------------------------------------
# IMAGE PREPROCESSING AND HISTORY STORAGE
# --------------------------------------------------

@app.route("/process/<filename>", methods=["POST"])
def process_uploaded_image(filename):

    try:

        # Download original image from AWS S3
        response = s3_client.get_object(
            Bucket=BUCKET_NAME,
            Key=f"uploads/{filename}"
        )

        image_bytes = response["Body"].read()

        # Get original image dimensions
        original_image = Image.open(BytesIO(image_bytes))
        width, height = original_image.size

        # Find the original image ID in MySQL
        connection = get_db_connection()
        image_id = None

        if connection:
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT id FROM images WHERE filename = %s",
                        (filename,)
                    )

                    result = cursor.fetchone()

                    if result:
                        image_id = result["id"]

                connection.close()

            except Exception:
                connection.close()
                raise

        # Register older S3 images that were uploaded
        # before MySQL integration
        if image_id is None:

            image_id = save_image_metadata(
                filename,
                f"uploads/{filename}",
                len(image_bytes),
                width,
                height
            )

        # Apply preprocessing operations
        processed_images = process_image(image_bytes)

        history_saved = True

        # Upload processed images to S3 and save history in MySQL
        for operation, processed_image in processed_images.items():

            processed_filename = (
                f"{filename.rsplit('.', 1)[0]}_{operation}.png"
            )

            processed_s3_key = f"processed/{processed_filename}"

            # Upload processed image to S3
            upload_processed_image(
                processed_image,
                processed_filename
            )

            # Save processing history in MySQL
            if image_id:

                saved = save_processing_history(
                    image_id,
                    operation,
                    processed_filename,
                    processed_s3_key
                )

                if not saved:
                    history_saved = False

            else:
                history_saved = False

        if history_saved:
            flash(
                "Image preprocessing completed successfully! "
                "Processing history saved in MySQL.",
                "success"
            )
        else:
            flash(
                "Image preprocessing completed, but some database "
                "records could not be saved.",
                "warning"
            )

    except Exception:
        app.logger.exception("Image preprocessing failed")
        flash(
            "Image preprocessing failed. Check server logs.",
            "error"
        )

    return redirect(url_for("dashboard"))


# --------------------------------------------------
# DELETE IMAGE FROM S3 AND MYSQL
# --------------------------------------------------

@app.route("/delete/<filename>", methods=["POST"])
def delete_uploaded_image(filename):

    try:

        # Delete original and processed images from S3
        delete_image(filename)

        # Delete original image record from MySQL
        # Processing history is deleted automatically
        # because of ON DELETE CASCADE.
        connection = get_db_connection()

        if connection:

            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM images WHERE filename = %s",
                        (filename,)
                    )

                    connection.commit()

                connection.close()

                flash(
                    "Image, processed versions, and database records "
                    "deleted successfully!",
                    "success"
                )

            except Exception:
                connection.rollback()
                connection.close()
                raise

        else:
            flash(
                "Image deleted from S3, but MySQL records "
                "could not be deleted.",
                "warning"
            )

    except Exception:
        app.logger.exception("Image deletion failed")
        flash(
            "Image deletion failed. Check server logs.",
            "error"
        )

    return redirect(url_for("dashboard"))


# --------------------------------------------------
# DASHBOARD
# --------------------------------------------------

@app.route("/dashboard")
def dashboard():

    # Get original images from S3
    images = [
        {
            "filename": key.split("/")[-1],
            "url": generate_image_url(key),
            **get_image_metadata(key)
        }
        for key in list_images()
    ]

    # Get processed images from S3
    processed_keys = list_processed_images()

    # Dashboard summary statistics
    total_uploaded = len(images)

    total_processed = len(processed_keys)

    total_storage = 0

    all_keys = list_images() + processed_keys

    for key in all_keys:

        metadata = s3_client.head_object(
            Bucket=BUCKET_NAME,
            Key=key
        )

        total_storage += metadata["ContentLength"]

    storage_mb = round(
        total_storage / (1024 * 1024),
        2
    )

    total_operations = total_processed

    # Group processed images with their original images
    comparison_groups = []

    for image in images:

        original_filename = image["filename"]
        original_name = original_filename.rsplit(".", 1)[0]

        outputs = []

        for key in processed_keys:

            processed_filename = key.split("/")[-1]

            if processed_filename.startswith(original_name + "_"):

                operation = processed_filename.rsplit(".", 1)[0]

                operation = operation[len(original_name) + 1:]

                valid_operations = {
                    "grayscale": "Grayscale",
                    "resized": "Resized",
                    "blurred": "Blurred",
                    "enhanced": "Enhanced"
                }

                operation_label = valid_operations.get(
                    operation.lower(),
                    operation.replace("_", " ").title()
                )

                outputs.append({
                    "filename": processed_filename,
                    "operation": operation_label,
                    "url": generate_image_url(key),
                    "download_url": generate_download_url(key),
                    **get_image_metadata(key)
                })

        comparison_groups.append({
            "original": {
                **image,
                "download_url": generate_download_url(
                    f"uploads/{original_filename}"
                )
            },
            "outputs": outputs
        })

    return render_template(
        "dashboard.html",
        images=images,
        processed_images=[
            {
                "filename": key.split("/")[-1],
                "url": generate_image_url(key),
                **get_image_metadata(key)
            }
            for key in processed_keys
        ],
        comparison_groups=comparison_groups,
        total_uploaded=total_uploaded,
        total_processed=total_processed,
        storage_mb=storage_mb,
        total_operations=total_operations
    )


# --------------------------------------------------
# FILE SIZE ERROR HANDLER
# --------------------------------------------------

@app.errorhandler(413)
def file_too_large(error):

    flash(
        "Image size must not exceed 5 MB.",
        "error"
    )

    return redirect(url_for("home"))


# --------------------------------------------------
# RUN FLASK APPLICATION
# --------------------------------------------------

if __name__ == "__main__":

    app.run(debug=True)
