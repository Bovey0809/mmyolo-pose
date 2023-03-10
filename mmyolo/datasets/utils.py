# Copyright (c) OpenMMLab. All rights reserved.
from typing import List, Sequence, Tuple, Union

import numpy as np
import torch
from mmengine.dataset import COLLATE_FUNCTIONS
from mmpose.datasets.datasets.utils import parse_pose_metainfo
from mmpose.structures.keypoint.transforms import flip_keypoints
from mmpose.evaluation.functional.nms import oks_iou

from ..registry import TASK_UTILS


@COLLATE_FUNCTIONS.register_module()
def yolov5_collate(data_batch: Sequence,
                   use_ms_training: bool = False) -> dict:
    """Rewrite collate_fn to get faster training speed.

    Args:
       data_batch (Sequence): Batch of data.
       use_ms_training (bool): Whether to use multi-scale training.
    """
    batch_imgs = []
    batch_bboxes_labels = []
    for i in range(len(data_batch)):
        datasamples = data_batch[i]['data_samples']
        inputs = data_batch[i]['inputs']

        gt_bboxes = datasamples.gt_instances.bboxes.tensor
        gt_labels = datasamples.gt_instances.labels
        batch_idx = gt_labels.new_full((len(gt_labels), 1), i)
        bboxes_labels = torch.cat((batch_idx, gt_labels[:, None], gt_bboxes),
                                  dim=1)
        batch_bboxes_labels.append(bboxes_labels)

        batch_imgs.append(inputs)
    if use_ms_training:
        return {
            'inputs': batch_imgs,
            'data_samples': torch.cat(batch_bboxes_labels, 0)
        }
    else:
        return {
            'inputs': torch.stack(batch_imgs, 0),
            'data_samples': torch.cat(batch_bboxes_labels, 0)
        }


@TASK_UTILS.register_module()
class BatchShapePolicy:
    """BatchShapePolicy is only used in the testing phase, which can reduce the
    number of pad pixels during batch inference.

    Args:
       batch_size (int): Single GPU batch size during batch inference.
           Defaults to 32.
       img_size (int): Expected output image size. Defaults to 640.
       size_divisor (int): The minimum size that is divisible
           by size_divisor. Defaults to 32.
       extra_pad_ratio (float):  Extra pad ratio. Defaults to 0.5.
    """

    def __init__(self,
                 batch_size: int = 32,
                 img_size: int = 640,
                 size_divisor: int = 32,
                 extra_pad_ratio: float = 0.5):
        self.batch_size = batch_size
        self.img_size = img_size
        self.size_divisor = size_divisor
        self.extra_pad_ratio = extra_pad_ratio

    def __call__(self, data_list: List[dict]) -> List[dict]:
        image_shapes = []
        for data_info in data_list:
            image_shapes.append((data_info['width'], data_info['height']))

        image_shapes = np.array(image_shapes, dtype=np.float64)

        n = len(image_shapes)  # number of images
        batch_index = np.floor(np.arange(n) / self.batch_size).astype(
            np.int64)  # batch index
        number_of_batches = batch_index[-1] + 1  # number of batches

        aspect_ratio = image_shapes[:, 1] / image_shapes[:, 0]  # aspect ratio
        irect = aspect_ratio.argsort()

        data_list = [data_list[i] for i in irect]

        aspect_ratio = aspect_ratio[irect]
        # Set training image shapes
        shapes = [[1, 1]] * number_of_batches
        for i in range(number_of_batches):
            aspect_ratio_index = aspect_ratio[batch_index == i]
            min_index, max_index = aspect_ratio_index.min(
            ), aspect_ratio_index.max()
            if max_index < 1:
                shapes[i] = [max_index, 1]
            elif min_index > 1:
                shapes[i] = [1, 1 / min_index]

        batch_shapes = np.ceil(
            np.array(shapes) * self.img_size / self.size_divisor +
            self.extra_pad_ratio).astype(np.int64) * self.size_divisor

        for i, data_info in enumerate(data_list):
            data_info['batch_shape'] = batch_shapes[batch_index[i]]

        return data_list


class Keypoints:
    METAINFO: dict = dict(from_file='configs/_base_/datasets/coco.py')
    metainfo = parse_pose_metainfo(METAINFO)

    @classmethod
    def _kpt_rescale(self, kpt, scale_factor: Tuple[float, float]):
        """Rescale the keypoints according to the scale factor.

        Args:
            kpt (np.ndarray): Keypoints to be rescaled. N x K x 2
            scale_factor (tuple[float]): Scale factor. (r1, r2)

        Returns:
            np.ndarray: Rescaled keypoints.
        """
        assert len(scale_factor) == 2
        assert kpt.shape[-1] == 2
        kpt[..., 0] = kpt[..., 0] * scale_factor[0]
        kpt[..., 1] = kpt[..., 1] * scale_factor[1]
        return kpt

    @classmethod
    def _kpt_translate(self, kpt, distances: Tuple[float, float]):
        """Translate the keypoints according to the given distances.

        Args:
            kpt (np.ndarray): Keypoints to be translated, in shape (N, K, 2).
            distances (tuple[float]): Distances to translate.

        Returns:
            np.ndarray: Translated keypoints.
        """
        assert len(distances) == 2
        assert kpt.shape[-1] == 2
        kpt[..., 0] = kpt[..., 0] + distances[0]
        kpt[..., 1] = kpt[..., 1] + distances[1]
        return kpt

    @classmethod
    def _kpt_clip(self, kpt, kpt_vis, img_shape: Tuple[int, int]) -> None:
        """Clip the keypoints, only change the visibility of the keypoints, not the coordinates.

        Args:
            kpt (np.ndarray): Keypoints to be clipped. N x K x 2
            kpt_vis (np.ndarray): Visibility of the keypoints. N x K
            img_shape (tuple[int]): Shape of the image.
        """
        assert len(img_shape) == 2
        assert kpt.shape[-1] == 2
        assert len(kpt_vis.shape) == 2
        # keypoints outside the image are not allowed
        flags = self._kpt_is_inside(kpt, img_shape, all_inside=False)
        # set visibility to 0 if the keypoint is outside the image
        kpt_vis[~flags] = 0
        return kpt_vis

    @classmethod
    def _kpt_is_inside(self,
                       kpt,
                       img_shape: Tuple[int, int],
                       all_inside: bool = False,
                       allowed_border: int = 0):
        """Check if the keypoints are inside the image.

        Args:
            kpt (np.ndarray): Keypoints to be checked.
            img_shape (tuple[int]): Shape of the image.
            all_inside (bool): Whether all keypoints should be inside the image.
            allowed_border (int): The border to allow for the keypoints.

        Returns:
            np.ndarray: Flags indicating whether each keypoint is inside the
                image. N x K
        """
        assert len(img_shape) == 2
        assert kpt.shape[-1] == 2
        if all_inside:
            flags = np.all((kpt[..., 0] >= allowed_border,
                            kpt[..., 0] < img_shape[1] - allowed_border,
                            kpt[..., 1] >= allowed_border,
                            kpt[..., 1] < img_shape[0] - allowed_border),
                           axis=0)
        else:
            flags = np.any((kpt[..., 0] >= allowed_border,
                            kpt[..., 0] < img_shape[1] - allowed_border,
                            kpt[..., 1] >= allowed_border,
                            kpt[..., 1] < img_shape[0] - allowed_border),
                           axis=0)
        return flags

    @classmethod
    def _affine_transform_pts(self, x, y, matrix):
        """Affine transformation for points.

        Args:
            x (np.ndarray): x coordinates of points.
            y (np.ndarray): y coordinates of points.
            matrix (np.ndarray): Affine transformation matrix.

        Returns:
            tuple[np.ndarray]: Transformed x and y coordinates.
        """
        x_t = matrix[0, 0] * x + matrix[0, 1] * y + matrix[0, 2]
        y_t = matrix[1, 0] * x + matrix[1, 1] * y + matrix[1, 2]
        return x_t, y_t

    @classmethod
    def _kpt_project(
            self, kpt, homography_matrix: Union[torch.Tensor,
                                                np.ndarray]) -> None:
        """Project the keypoints according to the homography matrix.

        Args:
            kpt (np.ndarray): Keypoints to be projected, in shape (N, K, 2).
            homography_matrix (torch.Tensor | np.ndarray): Homography matrix.
        """
        assert kpt.shape[-1] == 2
        kpt[..., 0::3], kpt[..., 1::3] = self._affine_transform_pts(
            kpt[..., 0::3], kpt[..., 1::3], homography_matrix)
        return kpt

    @classmethod
    def _kpt_flip(self, kpt, kpt_vis, img_shape: Tuple[int, int], direction) -> None:
        # default meta info for coco
        flip_indices = self.metainfo['flip_indices']
        kpt, kpt_vis = flip_keypoints(kpt, kpt_vis,
                                                  img_shape, flip_indices,
                                                  direction)
        return kpt, kpt_vis

    @classmethod
    def _kpt_area(self, kpt):
        """
        _kpt_area keypoints' rectangle's area.

        Maximum external rectangle area.

        Args:
            kpt (numpy.ndarray or Tensor): shape N x num_kps x dimension.
        """
        assert kpt.dim() == 3
        assert kpt.shape[-1] == 2 or kpt.shape[-1] == 3
        kpt = kpt[..., :2]
        x_min = kpt[..., 0].min(dim=-1)[0]
        x_max = kpt[..., 0].max(dim=-1)[0]
        y_min = kpt[..., 1].min(dim=-1)[0]
        y_max = kpt[..., 1].max(dim=-1)[0]
        return (x_max - x_min) * (y_max - y_min)
