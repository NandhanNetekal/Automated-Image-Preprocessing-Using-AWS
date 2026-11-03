
from PIL import Image, ImageFilter, ImageEnhance
from io import BytesIO


def convert_to_grayscale(image):
    """Convert image to grayscale."""
    return image.convert("L")


def resize_image(image, width=256, height=256):
    """Resize image to standard dimensions."""
    return image.resize((width, height))


def apply_gaussian_blur(image):
    """Apply Gaussian blur to image."""
    return image.filter(ImageFilter.GaussianBlur(radius=2))


def enhance_image(image):
    """Improve image contrast, brightness and sharpness."""
    image = ImageEnhance.Contrast(image).enhance(1.5)
    image = ImageEnhance.Brightness(image).enhance(1.2)
    image = ImageEnhance.Sharpness(image).enhance(1.5)

    return image


def process_image(image_bytes):
    """Apply all preprocessing operations to an image."""

    image = Image.open(BytesIO(image_bytes)).convert("RGB")

    processed_images = {
        "grayscale": convert_to_grayscale(image),
        "resized": resize_image(image),
        "blurred": apply_gaussian_blur(image),
        "enhanced": enhance_image(image)
    }

    return processed_images
