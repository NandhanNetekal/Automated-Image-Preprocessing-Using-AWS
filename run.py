
import os
import uuid
from io import BytesIO

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash
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
    get_original_filename,
    delete_image,
    s3_client,
    BUCKET_NAME
)

from app.services.db_service import (
    get_db_connection,
    save_image_metadata,
    replace_processing_history,
    get_processing_history_keys
)


# --------------------------------------------------
# FLASK CONFIGURATION
# --------------------------------------------------

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
                flash(
                    "Only JPG and PNG images are allowed.",
                    "error"
                )
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
                content_type,
                original_name
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

        return redirect(url_for("dashboard"))

    images = [
        {
            "filename": key.split("/")[-1],
            "url": generate_image_url(key)
        }
        for key in list_images()
    ]

    return render_template(
        "index.html",
        images=images
    )


# --------------------------------------------------
# IMAGE PREPROCESSING AND HISTORY STORAGE
# --------------------------------------------------

@app.route("/process/<filename>", methods=["POST"])
def process_uploaded_image(filename):
    try:
        response = s3_client.get_object(
            Bucket=BUCKET_NAME,
            Key=f"uploads/{filename}"
        )
        image_bytes = response["Body"].read()

        original_image = Image.open(BytesIO(image_bytes))
        width, height = original_image.size

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
            finally:
                connection.close()

        if image_id is None:
            image_id = save_image_metadata(
                filename,
                f"uploads/{filename}",
                len(image_bytes),
                width,
                height
            )

        selected_operations = request.form.getlist("operations")
        valid_operations = {"grayscale", "resized", "blurred", "enhanced"}
        selected_operations = [
            operation for operation in selected_operations
            if operation in valid_operations
        ]

        if not selected_operations:
            flash(
                "Please select at least one processing operation.",
                "warning"
            )
            return redirect(url_for("dashboard"))

        processed_images = process_image(image_bytes, selected_operations)

        if not processed_images:
            flash("No processed images were generated.", "warning")
            return redirect(url_for("dashboard"))

        original_name = filename.rsplit(".", 1)[0]
        history_records = []

        for operation, processed_image in processed_images.items():
            for extension in ("png", "jpg"):
                old_key = f"processed/{original_name}_{operation}.{extension}"
                s3_client.delete_object(
                    Bucket=BUCKET_NAME,
                    Key=old_key
                )

            processed_filename = f"{original_name}_{operation}.jpg"
            processed_s3_key = f"processed/{processed_filename}"

            upload_processed_image(
                processed_image,
                processed_filename,
                original_size_bytes=len(image_bytes)
            )

            history_records.append({
                "operation": operation,
                "processed_filename": processed_filename,
                "processed_s3_key": processed_s3_key
            })

        if image_id and replace_processing_history(image_id, history_records):
            flash(
                "Image preprocessing completed successfully! "
                "The dashboard now shows only the operations selected "
                "in this processing run.",
                "success"
            )
        else:
            flash(
                "Images were processed and uploaded, but the latest "
                "processing selection could not be saved in MySQL.",
                "warning"
            )

    except Exception:
        app.logger.exception("Image preprocessing failed")
        flash(
            "Image preprocessing failed. Check server logs.",
            "error"
        )

    return redirect(url_for("dashboard"))


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
            "display_name": get_original_filename(key),
            "url": generate_image_url(key),
            **get_image_metadata(key)
        }
        for key in list_images()
    ]

    # Show only processed files recorded for the latest run of each image.
    all_processed_keys = list(dict.fromkeys(list_processed_images()))
    latest_processed_keys = get_processing_history_keys()
    processed_keys = [
        key for key in all_processed_keys
        if key in latest_processed_keys
    ]

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

        # Get original image size directly from S3
        original_metadata = s3_client.head_object(
            Bucket=BUCKET_NAME,
            Key=f"uploads/{original_filename}"
        )

        original_size_bytes = original_metadata["ContentLength"]

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

                # Get processed image size directly from S3
                processed_metadata = s3_client.head_object(
                    Bucket=BUCKET_NAME,
                    Key=key
                )

                processed_size_bytes = processed_metadata["ContentLength"]

                # Calculate actual file-size reduction percentage
                if original_size_bytes > 0:

                    size_change_percent = round(
                        (
                            (original_size_bytes - processed_size_bytes)
                            / original_size_bytes
                        ) * 100,
                        2
                    )

                else:
                    size_change_percent = 0

                output_metadata = get_image_metadata(key)

                outputs.append({
                    "filename": processed_filename,
                    "display_name": operation_label,
                    "operation": operation_label,
                    "url": generate_image_url(key),
                    "download_url": generate_download_url(key),
                    "size_change_percent": abs(size_change_percent),
                    "size_change_label": (
                        "Size Reduction"
                        if size_change_percent >= 0
                        else "Size Increase"
                    ),
                    "size_change_text": (
                        f"{'Size Reduction' if size_change_percent >= 0 else 'Size Increase'}: "
                        f"{abs(size_change_percent)}%"
                    ),
                    "original_size_bytes": original_size_bytes,
                    "processed_size_bytes": processed_size_bytes,
                    **output_metadata
                })

        # Add original image and its processed outputs
        comparison_groups.append({
            "original": {
                **image,
                "download_url": generate_download_url(
                    f"uploads/{original_filename}"
                )
            },

            "outputs": outputs
        })

    # Render dashboard
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
