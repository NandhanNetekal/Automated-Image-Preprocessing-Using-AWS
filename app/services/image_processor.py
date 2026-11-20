from io import BytesIO

from PIL import Image, ImageFilter, ImageEnhance


def convert_to_grayscale(image):
    """Convert an image to grayscale."""
    return image.convert("L")


def resize_image(image, width=256, height=256):
    """Resize an image to the requested dimensions."""
    return image.resize((width, height))


def apply_gaussian_blur(image):
    """Apply Gaussian blur to an image."""
    return image.filter(ImageFilter.GaussianBlur(radius=2))


def enhance_image(image):
    """Improve contrast, brightness, and sharpness."""
    image = ImageEnhance.Contrast(image).enhance(1.5)
    image = ImageEnhance.Brightness(image).enhance(1.2)
    return ImageEnhance.Sharpness(image).enhance(1.5)


def process_image(image_bytes, selected_operations=None):
    """
    Apply only the selected preprocessing operations.

    If selected_operations is omitted, all supported operations are applied
    for backward compatibility with existing callers.
    """
    image = Image.open(BytesIO(image_bytes)).convert("RGB")

    operation_functions = {
        "grayscale": convert_to_grayscale,
        "resized": resize_image,
        "blurred": apply_gaussian_blur,
        "enhanced": enhance_image,
    }

    if selected_operations is None:
        selected_operations = list(operation_functions.keys())

    processed_images = {}
    for operation in selected_operations:
        function = operation_functions.get(operation)
        if function:
            processed_images[operation] = function(image)

    return processed_images
