from io import BytesIO

import pytest
from PIL import Image

from app.services.image_processing_service import (
    ImageProcessingError,
    ImageProcessingService,
    InvalidBoundingBoxError,
    ProductBoundingBox,
)


def create_test_image(
    *,
    width: int = 100,
    height: int = 80,
    mode: str = "RGB",
) -> bytes:
    image = Image.new(
        mode,
        (width, height),
        color=(220, 40, 40),
    )
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_process_without_bounding_box():
    service = ImageProcessingService()

    result = service.process(create_test_image())

    assert result.original_width == 100
    assert result.original_height == 80
    assert result.width == 100
    assert result.height == 80
    assert result.crop_applied is False
    assert result.data.startswith(b"\xff\xd8")


def test_process_crops_center_of_image():
    service = ImageProcessingService(
        crop_margin_ratio=0,
    )

    result = service.process(
        create_test_image(),
        ProductBoundingBox(
            x_min=0.25,
            y_min=0.25,
            x_max=0.75,
            y_max=0.75,
        ),
    )

    assert result.original_width == 100
    assert result.original_height == 80
    assert result.width == 50
    assert result.height == 40
    assert result.crop_applied is True


def test_process_rejects_invalid_image():
    service = ImageProcessingService()

    with pytest.raises(
        ImageProcessingError,
        match="không phải ảnh hợp lệ",
    ):
        service.process(b"not-an-image")


def test_process_rejects_invalid_bounding_box():
    service = ImageProcessingService()

    with pytest.raises(
        InvalidBoundingBoxError,
        match="tọa độ bounding box",
    ):
        service.process(
            create_test_image(),
            ProductBoundingBox(
                x_min=0.8,
                y_min=0.2,
                x_max=0.3,
                y_max=0.9,
            ),
        )


def test_process_limits_output_dimension():
    service = ImageProcessingService(
        max_dimension=200,
    )

    result = service.process(
        create_test_image(
            width=1000,
            height=500,
        )
    )

    assert result.width == 200
    assert result.height == 100


def test_process_replaces_transparent_background():
    service = ImageProcessingService()

    result = service.process(
        create_test_image(
            width=50,
            height=50,
            mode="RGBA",
        )
    )

    with Image.open(BytesIO(result.data)) as processed:
        assert processed.mode == "RGB"