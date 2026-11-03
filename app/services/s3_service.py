
import os
import boto3
from dotenv import load_dotenv
from io import BytesIO
from PIL import Image

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
BUCKET_NAME = os.getenv("S3_BUCKET_NAME")

s3_client = boto3.client(
    "s3",
    region_name="ap-south-1",
    endpoint_url="https://s3.ap-south-1.amazonaws.com"
)


def upload_image(file, filename, content_type):
    s3_client.upload_fileobj(
        file,
        BUCKET_NAME,
        f"uploads/{filename}",
        ExtraArgs={"ContentType": content_type}
    )

    return f"uploads/{filename}"


def list_images():
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
    return s3_client.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": BUCKET_NAME,
            "Key": key
        },
        ExpiresIn=3600
    )


def upload_processed_image(image, filename):
    """
    Upload a processed image to the S3 processed/ folder.
    """

    from io import BytesIO

    image_buffer = BytesIO()

    image_format = "PNG"

    image.save(image_buffer, format=image_format)

    image_buffer.seek(0)

    s3_client.upload_fileobj(
        image_buffer,
        BUCKET_NAME,
        f"processed/{filename}",
        ExtraArgs={"ContentType": "image/png"}
    )

    return f"processed/{filename}"

def list_processed_images():
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
    """
    Retrieve image dimensions, file size and date from S3.
    """

    response = s3_client.get_object(
        Bucket=BUCKET_NAME,
        Key=key
    )

    image_data = response["Body"].read()

    image = Image.open(BytesIO(image_data))
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

    from datetime import timezone, timedelta

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
    """
    Delete original image and all its processed versions from S3.
    """

    # Delete original image
    s3_client.delete_object(
        Bucket=BUCKET_NAME,
        Key=f"uploads/{filename}"
    )

    # Find all processed versions
    original_name = filename.rsplit(".", 1)[0]
    prefix = f"processed/{original_name}_"

    response = s3_client.list_objects_v2(
        Bucket=BUCKET_NAME,
        Prefix=prefix
    )

    # Delete processed versions
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