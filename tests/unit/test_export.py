import pytest
import numpy as np
import PIL

from armory.utils.export import (
    ImageClassificationExporter,
    ObjectDetectionExporter,
    VideoClassificationExporter,
    VideoTrackingExporter,
    So2SatExporter,
)

# Mark all tests in this file as `unit`
pytestmark = pytest.mark.unit


def test_image_classification_export(tmp_path):
    random_x = np.random.rand(32, 32, 3)
    exporter = ImageClassificationExporter(base_output_dir=tmp_path)
    pil_img = exporter.get_sample(random_x)
    assert isinstance(pil_img, PIL.Image.Image)


def test_object_detection_export(tmp_path):
    random_x = np.random.rand(32, 32, 3)
    exporter = ObjectDetectionExporter(base_output_dir=tmp_path)
    pil_img = exporter.get_sample(random_x)
    assert isinstance(pil_img, PIL.Image.Image)

    y = {
        "labels": np.array([1.0]),
        "boxes": np.array([[0.0, 0.0, 1.0, 1.0]]).astype(np.float32),
    }
    y_pred = {
        "scores": np.array([1.0]),
        "labels": np.array([1.0]),
        "boxes": np.array([[0.0, 0.0, 1.0, 1.0]]).astype(np.float32),
    }

    pil_img_with_both_boxes = exporter.get_sample(
        random_x, with_boxes=True, y_i=y, y_i_pred=y_pred
    )
    assert isinstance(pil_img_with_both_boxes, PIL.Image.Image)

    pil_img_with_gt_boxes = exporter.get_sample(random_x, with_boxes=True, y_i=y)
    assert isinstance(pil_img_with_gt_boxes, PIL.Image.Image)

    pil_img_with_pred_boxes = exporter.get_sample(
        random_x, with_boxes=True, y_i_pred=y_pred
    )
    assert isinstance(pil_img_with_pred_boxes, PIL.Image.Image)


def test_video_classification_export(tmp_path):
    num_frames = 12
    random_x = np.random.rand(num_frames, 32, 32, 3)
    exporter = VideoClassificationExporter(base_output_dir=tmp_path, frame_rate=10)
    pil_img_list = exporter.get_sample(random_x)
    assert isinstance(pil_img_list, list)
    assert len(pil_img_list) == num_frames
    for img in pil_img_list:
        assert isinstance(img, PIL.Image.Image)


def test_video_tracking_export(tmp_path):
    num_frames = 12
    random_x = np.random.rand(num_frames, 32, 32, 3)
    exporter = VideoTrackingExporter(base_output_dir=tmp_path, frame_rate=10)
    pil_img_list = exporter.get_sample(random_x)
    assert isinstance(pil_img_list, list)
    assert len(pil_img_list) == num_frames
    for img in pil_img_list:
        assert isinstance(img, PIL.Image.Image)

    y = {"boxes": np.ones((num_frames, 4)).astype(np.float32)}
    y_pred = {"boxes": np.ones((num_frames, 4)).astype(np.float32)}

    pil_img_with_boxes_list = exporter.get_sample(
        random_x, with_boxes=True, y_i_pred=y_pred, y_i=y
    )

    assert isinstance(pil_img_with_boxes_list, list)
    assert len(pil_img_list) == num_frames
    for img in pil_img_list:
        assert isinstance(img, PIL.Image.Image)


def test_so2sat_export(tmp_path):
    random_x = np.random.rand(32, 32, 14)
    exporter = So2SatExporter(base_output_dir=tmp_path)
    sample_vh = exporter.get_sample(random_x, modality="vh")
    assert isinstance(sample_vh, PIL.Image.Image)

    sample_vv = exporter.get_sample(random_x, modality="vv")
    assert isinstance(sample_vv, PIL.Image.Image)

    samples_eo = exporter.get_sample(random_x, modality="eo")
    assert isinstance(samples_eo, list)
    assert len(samples_eo) == 10
    for i in samples_eo:
        assert isinstance(i, PIL.Image.Image)
