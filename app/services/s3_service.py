import os
from io import BytesIO
from datetime import timezone, timedelta

import boto3
from dotenv import load_dotenv
from PIL import Image

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
BUCKET_NAME = os.getenv("S3_BUCKET_NAME")

s3_client = boto3.client(
    "s3",
    region_name=AWS_REGION,
    endpoint_url=f"https://s3.{AWS_REGION}.amazonaws.com"
)


def upload_image(file, filename, content_type, original_name=None):
    """Upload an original image to the uploads/ folder in S3."""
    extra_args = {
        "ContentType": content_type,
        "Metadata": {
            "original-filename": original_name or filename
        }
    }

    s3_client.upload_fileobj(
        file,
        BUCKET_NAME,
        f"uploads/{filename}",
        ExtraArgs=extra_args
    )

    return f"uploads/{filename}"


def get_original_filename(key):
    """Retrieve the original filename saved in S3 object metadata."""
    response = s3_client.head_object(
        Bucket=BUCKET_NAME,
        Key=key
    )

    return response.get("Metadata", {}).get(
        "original-filename",
        key.split("/")[-1]
    )


def list_images():
    """Return all original image keys from S3."""
    response = s3_client.list_objects_v2(
        Bucket=BUCKET_NAME,
        Prefix="uploads/"
    )

    return [
        item["Key"]
        for item in response.get("Contents", [])
        if item["Key"] != "uploads/"
    ]


def generate_image_url(key):
    """Generate a temporary URL for viewing an S3 image."""
    return s3_client.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": BUCKET_NAME,
            "Key": key
        },
        ExpiresIn=3600
    )


def upload_processed_image(image, filename, original_size_bytes=None):
    """
    Compress and upload a processed image to S3.

    First tries JPEG quality settings at the original dimensions.
    If the result is still larger than the original, progressively
    reduces dimensions until the output fits or the fallback limit
    is reached.
    """
    if image.mode in ("RGBA", "LA", "P"):
        image = image.convert("RGB")
    elif image.mode != "RGB":
        image = image.convert("RGB")

    quality_levels = [85, 75, 65, 55, 45, 35, 25]
    scale_levels = [1.00, 0.95, 0.90, 0.85, 0.80, 0.75, 0.70, 0.65, 0.60, 0.55, 0.50]

    best_buffer = None
    best_size = None

    for scale in scale_levels:
        if scale == 1.00:
            candidate_image = image
        else:
            new_width = max(1, int(image.width * scale))
            new_height = max(1, int(image.height * scale))
            candidate_image = image.resize(
                (new_width, new_height),
                Image.Resampling.LANCZOS
            )

        for quality in quality_levels:
            image_buffer = BytesIO()

            candidate_image.save(
                image_buffer,
                format="JPEG",
                quality=quality,
                optimize=True,
                progressive=True,
                subsampling=2
            )

            current_size = image_buffer.tell()

            # Keep the smallest version as a fallback if the target
            # cannot be reached with the tested quality and dimensions.
            if best_size is None or current_size < best_size:
                best_buffer = BytesIO(image_buffer.getvalue())
                best_size = current_size

            # Stop at the first version that fits. This prioritizes
            # keeping the original dimensions, then the highest quality.
            if original_size_bytes is not None and current_size <= original_size_bytes:
                best_buffer = BytesIO(image_buffer.getvalue())
                best_size = current_size
                break

            # Without an original-size target, use quality 75 at full size.
            if original_size_bytes is None and scale == 1.00 and quality == 75:
                best_buffer = BytesIO(image_buffer.getvalue())
                best_size = current_size
                break

        if original_size_bytes is None and scale == 1.00:
            break

        if original_size_bytes is not None and best_size <= original_size_bytes:
            break

    best_buffer.seek(0)

    filename = filename.rsplit(".", 1)[0] + ".jpg"
    s3_key = f"processed/{filename}"

    s3_client.upload_fileobj(
        best_buffer,
        BUCKET_NAME,
        s3_key,
        ExtraArgs={"ContentType": "image/jpeg"}
    )

    return s3_key


def list_processed_images():
    """Return all processed image keys from S3."""
    response = s3_client.list_objects_v2(
        Bucket=BUCKET_NAME,
        Prefix="processed/"
    )

    return [
        item["Key"]
        for item in response.get("Contents", [])
        if item["Key"] != "processed/"
    ]


def generate_download_url(key):
    """Generate a temporary download URL for an S3 object."""
    return s3_client.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": BUCKET_NAME,
            "Key": key,
            "ResponseContentDisposition": "attachment"
        },
        ExpiresIn=3600
    )


def get_image_metadata(key):
    """Retrieve image dimensions, file size and upload/processing date."""
    response = s3_client.get_object(
        Bucket=BUCKET_NAME,
        Key=key
    )

    image_data = response["Body"].read()

    with Image.open(BytesIO(image_data)) as image:
        width, height = image.size

    file_size = len(image_data)

    if file_size >= 1024 * 1024:
        size_display = f"{file_size / (1024 * 1024):.2f} MB"
    else:
        size_display = f"{file_size / 1024:.2f} KB"

    head_response = s3_client.head_object(
        Bucket=BUCKET_NAME,
        Key=key
    )

    last_modified = head_response["LastModified"]
    ist = timezone(timedelta(hours=5, minutes=30))

    date_time = last_modified.astimezone(ist).strftime(
        "%d-%m-%Y %I:%M %p"
    )

    return {
        "width": width,
        "height": height,
        "dimensions": f"{width} × {height}",
        "file_size": size_display,
        "date_time": date_time
    }


def delete_image(filename):
    """Delete an original image and all its processed versions from S3."""
    s3_client.delete_object(
        Bucket=BUCKET_NAME,
        Key=f"uploads/{filename}"
    )

    original_name = filename.rsplit(".", 1)[0]
    prefix = f"processed/{original_name}_"

    response = s3_client.list_objects_v2(
        Bucket=BUCKET_NAME,
        Prefix=prefix
    )

    objects = [
        {"Key": item["Key"]}
        for item in response.get("Contents", [])
    ]

    if objects:
        s3_client.delete_objects(
            Bucket=BUCKET_NAME,
            Delete={"Objects": objects}
        )

    return True
