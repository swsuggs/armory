import os
from typing import Optional

from art.attacks.evasion.adversarial_patch.adversarial_patch_pytorch import (
    AdversarialPatchPyTorch,
)
import cv2
import numpy as np
import torch

# GIF HACK imports -- stuff needed to inherit ART generate
from tqdm.auto import trange
from typing import Optional, Tuple, Union, TYPE_CHECKING
from art.utils import check_and_transform_label_format, is_probability, to_categorical

from armory.art_experimental.attacks.carla_obj_det_utils import (
    linear_depth_to_rgb,
    rgb_depth_to_linear,
    linear_to_log,
    log_to_linear,
)
from armory.logs import log


class AdversarialPatchPyTorch_Hack(AdversarialPatchPyTorch):
   
    def generate(  # type: ignore
        self, x: np.ndarray, y: Optional[np.ndarray] = None, model=None, **kwargs
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Generate an adversarial patch and return the patch and its mask in arrays.

        :param x: An array with the original input images of shape NCHW or input videos of shape NFCHW.
        :param y: An array with the original true labels.
        :param mask: An boolean array of shape equal to the shape of a single samples (1, H, W) or the shape of `x`
                     (N, H, W) without their channel dimensions. Any features for which the mask is True can be the
                     center location of the patch during sampling.
        :type mask: `np.ndarray`
        :return: An array with adversarial patch and an array of the patch mask.
        """
        import torch

        shuffle = kwargs.get("shuffle", True)
        mask = kwargs.get("mask")
        if mask is not None:
            mask = mask.copy()
        mask = self._check_mask(mask=mask, x=x)

        if self.patch_location is not None and mask is not None:
            raise ValueError("Masks can only be used if the `patch_location` is `None`.")

        if y is None:  # pragma: no cover
            logger.info("Setting labels to estimator predictions and running untargeted attack because `y=None`.")
            y = to_categorical(np.argmax(self.estimator.predict(x=x), axis=1), nb_classes=self.estimator.nb_classes)

        if hasattr(self.estimator, "nb_classes"):
            y = check_and_transform_label_format(labels=y, nb_classes=self.estimator.nb_classes)

            # check if logits or probabilities
            y_pred = self.estimator.predict(x=x[[0]])

            if is_probability(y_pred):
                self.use_logits = False
            else:
                self.use_logits = True

        if isinstance(y, np.ndarray):
            x_tensor = torch.Tensor(x)
            y_tensor = torch.Tensor(y)

            if mask is None:
                dataset = torch.utils.data.TensorDataset(x_tensor, y_tensor)
                data_loader = torch.utils.data.DataLoader(
                    dataset=dataset,
                    batch_size=self.batch_size,
                    shuffle=shuffle,
                    drop_last=False,
                )
            else:
                mask_tensor = torch.Tensor(mask)
                dataset = torch.utils.data.TensorDataset(x_tensor, y_tensor, mask_tensor)
                data_loader = torch.utils.data.DataLoader(
                    dataset=dataset,
                    batch_size=self.batch_size,
                    shuffle=shuffle,
                    drop_last=False,
                )
        else:

            class ObjectDetectionDataset(torch.utils.data.Dataset):
                """
                Object detection dataset in PyTorch.
                """

                def __init__(self, x, y):
                    self.x = x
                    self.y = y

                def __len__(self):
                    return self.x.shape[0]

                def __getitem__(self, idx):
                    img = torch.from_numpy(self.x[idx])

                    target = {}
                    target["boxes"] = torch.from_numpy(self.y[idx]["boxes"])
                    target["labels"] = torch.from_numpy(self.y[idx]["labels"])
                    target["scores"] = torch.from_numpy(self.y[idx]["scores"])

                    return img, target

            class ObjectDetectionDatasetMask(torch.utils.data.Dataset):
                """
                Object detection dataset in PyTorch.
                """

                def __init__(self, x, y, mask):
                    self.x = x
                    self.y = y
                    self.mask = mask

                def __len__(self):
                    return self.x.shape[0]

                def __getitem__(self, idx):
                    img = torch.from_numpy(self.x[idx])

                    target = {}
                    target["boxes"] = torch.from_numpy(y[idx]["boxes"])
                    target["labels"] = torch.from_numpy(y[idx]["labels"])
                    target["scores"] = torch.from_numpy(y[idx]["scores"])
                    mask_i = torch.from_numpy(self.mask[idx])

                    return img, target, mask_i

            dataset_object_detection: Union[ObjectDetectionDataset, ObjectDetectionDatasetMask]
            if mask is None:
                dataset_object_detection = ObjectDetectionDataset(x, y)
            else:
                dataset_object_detection = ObjectDetectionDatasetMask(x, y, mask)

            data_loader = torch.utils.data.DataLoader(
                dataset=dataset_object_detection,
                batch_size=self.batch_size,
                shuffle=shuffle,
                drop_last=False,
            )

        ### GIF HACK begin
        from armory.metrics.task import carla_od_AP_per_class, carla_od_hallucinations_per_image
        from armory.instrument.export import ObjectDetectionExporter
        OD = ObjectDetectionExporter(
            "/workspace/exports/",  # docker container
            default_export_kwargs={"with_boxes": True, "classes_to_skip": [4]},
        )

        for i_iter in trange(self.max_iter, desc="Adversarial Patch PyTorch", disable=not self.verbose):
            if mask is None:
                for images, target in data_loader:
                    images = images.to(self.estimator.device)
                    if isinstance(target, torch.Tensor):
                        target = target.to(self.estimator.device)
                    else:
                        target["boxes"] = target["boxes"].to(self.estimator.device)
                        target["labels"] = target["labels"].to(self.estimator.device)
                        target["scores"] = target["scores"].to(self.estimator.device)
                    _ = self._train_step(images=images, target=target, mask=None)
            else:
                for images, target, mask_i in data_loader:
                    images = images.to(self.estimator.device)
                    if isinstance(target, torch.Tensor):
                        target = target.to(self.estimator.device)
                    else:
                        target["boxes"] = target["boxes"].to(self.estimator.device)
                        target["labels"] = target["labels"].to(self.estimator.device)
                        target["scores"] = target["scores"].to(self.estimator.device)
                    mask_i = mask_i.to(self.estimator.device)
                    _ = self._train_step(images=images, target=target, mask=mask_i)

            if model is not None:
                if i_iter%10 == 0:  ## Set how frequently to export images
                    x_patched = (
                            self._random_overlay(
                        images=torch.from_numpy(x).to(self.estimator.device), patch=self._patch, mask=mask
                    )
                    .detach()
                    .cpu()
                    .numpy()
                    )
                
                    y_pred = model.predict(x_patched)
                    hals = carla_od_hallucinations_per_image(y, y_pred)
                    mAP = carla_od_AP_per_class(y, y_pred)
                    map_ = np.mean([g for g in mAP["class"].values() if g != 0])
                    # absent classes should not be included... but they were some of the time??

                    mAP = mAP["mean"]
                    y_pred[0]["hallucs"]=hals  # put these values into y so they can be
                    y_pred[0]["map"]=map_      # drawn on the exported images
                    y_pred[0]["iters"]=i_iter

                    OD.export(x_patched[0], f"generation_{i_iter}", y=y[0], y_pred=y_pred[0])

            # GIF HACK end I think


            # Write summary
            if self.summary_writer is not None:  # pragma: no cover
                x_patched = (
                    self._random_overlay(
                        images=torch.from_numpy(x).to(self.estimator.device), patch=self._patch, mask=mask
                    )
                    .detach()
                    .cpu()
                    .numpy()
                )

                self.summary_writer.update(
                    batch_id=0,
                    global_step=i_iter,
                    grad=None,
                    patch=self._patch,
                    estimator=self.estimator,
                    x=x_patched,
                    y=y,
                    targeted=self.targeted,
                )

        if self.summary_writer is not None:
            self.summary_writer.reset()

        return (
            self._patch.detach().cpu().numpy(),
            self._get_circular_patch_mask(nb_samples=1).cpu().numpy()[0],
        )

class CARLAAdversarialPatchPyTorch(AdversarialPatchPyTorch_Hack):  # GIF HACK: inherit hacked class
    """
    Apply patch attack to RGB channels and (optionally) masked PGD attack to depth channels.
    """

    def __init__(self, estimator, **kwargs):

        # Maximum depth perturbation from a flat patch
        self.depth_delta_meters = kwargs.pop("depth_delta_meters", 3)
        self.learning_rate_depth = kwargs.pop("learning_rate_depth", 0.0001)
        self.depth_perturbation = None
        self.min_depth = None
        self.max_depth = None
        self.patch_base_image = kwargs.pop("patch_base_image", None)

        # HSV bounds are user-defined to limit perturbation regions
        self.hsv_lower_bound = np.array(
            kwargs.pop("hsv_lower_bound", [0, 0, 0])
        )  # [0, 0, 0] means unbounded below
        self.hsv_upper_bound = np.array(
            kwargs.pop("hsv_upper_bound", [255, 255, 255])
        )  # [255, 255, 255] means unbounded above

        super().__init__(estimator=estimator, **kwargs)

    def create_initial_image(self, size, hsv_lower_bound, hsv_upper_bound):
        """
        Create initial patch based on a user-defined image and
        create perturbation mask based on HSV bounds
        """
        module_path = globals()["__file__"]
        # user-defined image is assumed to reside in the same location as the attack module
        patch_base_image_path = os.path.abspath(
            os.path.join(os.path.join(module_path, "../"), self.patch_base_image)
        )

        im = cv2.imread(patch_base_image_path)
        im = cv2.resize(im, size)
        im = cv2.cvtColor(im, cv2.COLOR_BGR2RGB)

        hsv = cv2.cvtColor(im, cv2.COLOR_RGB2HSV)
        # find the colors within the boundaries
        mask = cv2.inRange(hsv, hsv_lower_bound, hsv_upper_bound)
        mask = np.expand_dims(mask, 2)
        # cv2.imwrite(
        #     "mask.png", mask
        # )  # visualize perturbable regions. Comment out if not needed.

        patch_base = np.transpose(im, (2, 0, 1))
        patch_base = patch_base / 255.0
        mask = np.transpose(mask, (2, 0, 1))
        mask = mask / 255.0
        return patch_base, mask

    def _train_step(
        self,
        images: "torch.Tensor",
        target: "torch.Tensor",
        mask: Optional["torch.Tensor"] = None,
    ) -> "torch.Tensor":
        import torch  # lgtm [py/repeated-import]

        self.estimator.model.zero_grad()
        loss = self._loss(images, target, mask)
        loss.backward(retain_graph=True)

        if self._optimizer_string == "pgd":
            patch_grads = self._patch.grad
            patch_gradients = patch_grads.sign() * self.learning_rate * self.patch_mask

            if images.shape[-1] == 6:
                depth_grads = self.depth_perturbation.grad
                if self.depth_type == "log":
                    depth_log = (
                        self.depth_perturbation
                        + depth_grads.sign() * self.learning_rate_depth
                    )
                else:
                    grads_linear = rgb_depth_to_linear(
                        depth_grads[:, 0, :, :],
                        depth_grads[:, 1, :, :],
                        depth_grads[:, 2, :, :],
                    )
                    depth_linear = rgb_depth_to_linear(
                        self.depth_perturbation[:, 0, :, :],
                        self.depth_perturbation[:, 1, :, :],
                        self.depth_perturbation[:, 2, :, :],
                    )
                    depth_linear = (
                        depth_linear + grads_linear.sign() * self.learning_rate_depth
                    )

            with torch.no_grad():
                self._patch[:] = torch.clamp(
                    self._patch + patch_gradients,
                    min=self.estimator.clip_values[0],
                    max=self.estimator.clip_values[1],
                )

                if images.shape[-1] == 6:
                    images_depth = torch.permute(images[:, :, :, 3:], (0, 3, 1, 2))
                    if self.depth_type == "log":
                        perturbed_images = torch.clamp(
                            images_depth + depth_log,
                            min=self.min_depth,
                            max=self.max_depth,
                        )
                        self.depth_perturbation[:] = perturbed_images - images_depth
                    else:
                        images_depth_linear = rgb_depth_to_linear(
                            images_depth[:, 0, :, :],
                            images_depth[:, 1, :, :],
                            images_depth[:, 2, :, :],
                        )
                        depth_linear = torch.clamp(
                            images_depth_linear + depth_linear,
                            min=self.min_depth,
                            max=self.max_depth,
                        )
                        depth_r, depth_g, depth_b = linear_depth_to_rgb(depth_linear)
                        perturbed_images = torch.stack(
                            [depth_r, depth_g, depth_b], dim=1
                        )
                        self.depth_perturbation[:] = perturbed_images - images_depth

        else:
            raise ValueError(
                "Adam optimizer for CARLA Adversarial Patch not supported."
            )

        return loss

    def _get_circular_patch_mask(
        self, nb_samples: int, sharpness: int = 40
    ) -> "torch.Tensor":
        """
        Return a circular patch mask.
        """
        import torch  # lgtm [py/repeated-import]

        image_mask = np.ones(
            (self.patch_shape[self.i_h_patch], self.patch_shape[self.i_w_patch])
        )

        image_mask = np.expand_dims(image_mask, axis=0)
        image_mask = np.broadcast_to(image_mask, self.patch_shape)
        image_mask = torch.Tensor(np.array(image_mask)).to(self.estimator.device)
        image_mask = torch.stack([image_mask] * nb_samples, dim=0)
        return image_mask

    def _random_overlay(
        self,
        images: "torch.Tensor",
        patch: "torch.Tensor",
        scale: Optional[float] = None,
        mask: Optional["torch.Tensor"] = None,
    ) -> "torch.Tensor":
        import torch  # lgtm [py/repeated-import]
        import torchvision

        # Ensure channels-first
        if not self.estimator.channels_first:
            images = torch.permute(images, (0, 3, 1, 2))

        nb_samples = images.shape[0]

        images_rgb = images[:, :3, :, :]
        if images.shape[1] == 6:
            images_depth = images[:, 3:, :, :]

        image_mask = self._get_circular_patch_mask(nb_samples=nb_samples)
        image_mask = image_mask.float()

        self.image_shape = images_rgb.shape[1:]

        pad_h_before = int(
            (self.image_shape[self.i_h] - image_mask.shape[self.i_h_patch + 1]) / 2
        )
        pad_h_after = int(
            self.image_shape[self.i_h]
            - pad_h_before
            - image_mask.shape[self.i_h_patch + 1]
        )

        pad_w_before = int(
            (self.image_shape[self.i_w] - image_mask.shape[self.i_w_patch + 1]) / 2
        )
        pad_w_after = int(
            self.image_shape[self.i_w]
            - pad_w_before
            - image_mask.shape[self.i_w_patch + 1]
        )

        image_mask = torchvision.transforms.functional.pad(
            img=image_mask,
            padding=[pad_w_before, pad_h_before, pad_w_after, pad_h_after],
            fill=0,
            padding_mode="constant",
        )

        if self.nb_dims == 4:
            image_mask = torch.unsqueeze(image_mask, dim=1)
            image_mask = torch.repeat_interleave(
                image_mask, dim=1, repeats=self.input_shape[0]
            )

        image_mask = image_mask.float()

        patch = patch.float()
        padded_patch = torch.stack([patch] * nb_samples)

        padded_patch = torchvision.transforms.functional.pad(
            img=padded_patch,
            padding=[pad_w_before, pad_h_before, pad_w_after, pad_h_after],
            fill=0,
            padding_mode="constant",
        )

        if self.nb_dims == 4:
            padded_patch = torch.unsqueeze(padded_patch, dim=1)
            padded_patch = torch.repeat_interleave(
                padded_patch, dim=1, repeats=self.input_shape[0]
            )

        padded_patch = padded_patch.float()

        image_mask_list = []
        padded_patch_list = []

        for i_sample in range(nb_samples):

            image_mask_i = image_mask[i_sample]

            height = padded_patch.shape[self.i_h + 1]
            width = padded_patch.shape[self.i_w + 1]

            startpoints = [
                [pad_w_before, pad_h_before],
                [width - pad_w_after - 1, pad_h_before],
                [width - pad_w_after - 1, height - pad_h_after - 1],
                [pad_w_before, height - pad_h_after - 1],
            ]
            endpoints = self.gs_coords[
                i_sample
            ]  # [topleft, topright, botright, botleft]
            enlarged_coords = np.copy(
                endpoints
            )  # enlarge the green screen coordinates a bit to fully cover the screen
            pad_amt_x = int(0.03 * (enlarged_coords[2, 0] - enlarged_coords[0, 0]))
            pad_amt_y = int(0.03 * (enlarged_coords[2, 1] - enlarged_coords[0, 1]))
            enlarged_coords[0, 0] -= pad_amt_x
            enlarged_coords[0, 1] -= pad_amt_y
            enlarged_coords[1, 0] += pad_amt_x
            enlarged_coords[1, 1] -= pad_amt_y
            enlarged_coords[2, 0] += pad_amt_x
            enlarged_coords[2, 1] += pad_amt_y
            enlarged_coords[3, 0] -= pad_amt_x
            enlarged_coords[3, 1] += pad_amt_y
            endpoints = enlarged_coords

            image_mask_i = torchvision.transforms.functional.perspective(
                img=image_mask_i,
                startpoints=startpoints,
                endpoints=endpoints,
                interpolation=2,
                fill=0,  # None
            )

            image_mask_list.append(image_mask_i)

            padded_patch_i = padded_patch[i_sample]

            padded_patch_i = torchvision.transforms.functional.perspective(
                img=padded_patch_i,
                startpoints=startpoints,
                endpoints=endpoints,
                interpolation=2,
                fill=0,  # None
            )

            padded_patch_list.append(padded_patch_i)

        image_mask = torch.stack(image_mask_list, dim=0)
        padded_patch = torch.stack(padded_patch_list, dim=0)
        inverted_mask = (
            torch.from_numpy(np.ones(shape=image_mask.shape, dtype=np.float32)).to(
                self.estimator.device
            )
            - image_mask
        )

        foreground_mask = torch.all(
            torch.tensor(self.binarized_patch_mask == 0), dim=-1, keepdim=True
        ).to(self.estimator.device)
        foreground_mask = torch.permute(foreground_mask, (2, 0, 1))
        foreground_mask = torch.unsqueeze(foreground_mask, dim=0)

        # Adjust green screen brightness
        v_avg = (
            0.5647  # average V value (in HSV) for the green screen, which is #00903a
        )
        green_screen = images_rgb * image_mask
        values, _ = torch.max(green_screen, dim=1, keepdim=True)
        values_ratio = values / v_avg
        values_ratio = torch.repeat_interleave(values_ratio, dim=1, repeats=3)

        patched_images = (
            images_rgb * inverted_mask
            + padded_patch * values_ratio * image_mask
            - padded_patch * values_ratio * foreground_mask * image_mask
            + images_rgb * foreground_mask * image_mask
        )

        patched_images = torch.clamp(
            patched_images,
            min=self.estimator.clip_values[0],
            max=self.estimator.clip_values[1],
        )

        if not self.estimator.channels_first:
            patched_images = torch.permute(patched_images, (0, 2, 3, 1))

        # Apply perturbation to depth channels
        if images.shape[1] == 6:
            perturbed_images = images_depth + self.depth_perturbation * ~foreground_mask

            perturbed_images = torch.clamp(
                perturbed_images,
                min=self.estimator.clip_values[0],
                max=self.estimator.clip_values[1],
            )

            if not self.estimator.channels_first:
                perturbed_images = torch.permute(perturbed_images, (0, 2, 3, 1))

            return torch.cat([patched_images, perturbed_images], dim=-1)

        return patched_images

    def generate(self, x, model, y=None, y_patch_metadata=None):
        """
        param x: Sample images. For single-modality, shape=(NHW3). For multimodality, shape=(NHW6)
        param y: [Optional] Sample labels. List of dictionaries,
            ith dictionary contains bounding boxes, class labels, and class scores
        param y_patch_metadata: Patch metadata. List of N dictionaries, ith dictionary contains patch metadata for x[i]
        """

        if x.shape[0] > 1:
            log.info("To perform per-example patch attack, batch size must be 1")
        assert x.shape[-1] in [3, 6], "x must have either 3 or 6 color channels"

        num_imgs = x.shape[0]
        attacked_images = []
        for i in range(num_imgs):
            # Adversarial patch attack, when used for object detection, requires ground truth
            y_gt = dict()
            y_gt["labels"] = y[i]["labels"]
            non_patch_idx = np.where(
                y_gt["labels"] != 4
            )  # exclude the patch class, which doesn't exist in the training data
            y_gt["boxes"] = y[i]["boxes"][non_patch_idx]
            y_gt["labels"] = y_gt["labels"][non_patch_idx]
            y_gt["scores"] = np.ones(len(y_gt["labels"]), dtype=np.float32)

            gs_coords = y_patch_metadata[i]["gs_coords"]  # patch coordinates
            self.gs_coords = [gs_coords]
            patch_width = np.max(gs_coords[:, 0]) - np.min(gs_coords[:, 0])
            patch_height = np.max(gs_coords[:, 1]) - np.min(gs_coords[:, 1])
            self.patch_shape = (
                3,
                patch_height,
                patch_width,
            )

            # Use this mask to embed patch into the background in the event of occlusion
            self.binarized_patch_mask = y_patch_metadata[i]["mask"]

            # Eval7 contains a mixture of patch locations.
            # Patches that lie flat on the sidewalk or street are constrained to 0.03m depth perturbation, and they are best used to create disappearance errors.
            # Patches located elsewhere (i.e., that do not impede pedestrian/vehicle motion) are constrained to 3m depth perturbation, and they are best used to create hallucinations.
            # Therefore, the depth perturbation bound for each patch is input-dependent.
            if x.shape[-1] == 6:
                if "max_depth_perturb_meters" in y_patch_metadata[i].keys():
                    self.depth_delta_meters = y_patch_metadata[i][
                        "max_depth_perturb_meters"
                    ]
                    log.info(
                        'This dataset contains input-dependent depth perturbation bounds, and the user-defined "depth_delta_meters" has been reset to {} meters'.format(
                            y_patch_metadata[i]["max_depth_perturb_meters"]
                        )
                    )

            # self._patch needs to be re-initialized with the correct shape
            if self.patch_base_image is not None:
                patch_init, patch_mask = self.create_initial_image(
                    (patch_width, patch_height),
                    self.hsv_lower_bound,
                    self.hsv_upper_bound,
                )
            else:
                patch_init = np.random.randint(0, 255, size=self.patch_shape) / 255
                patch_mask = np.ones_like(patch_init)

            self._patch = torch.tensor(
                patch_init, requires_grad=True, device=self.estimator.device
            )
            self.patch_mask = torch.Tensor(patch_mask).to(self.estimator.device)

            # initialize depth variables
            if x.shape[-1] == 6:
                # check if depth image is log-depth
                if np.all(x[i, :, :, 3] == x[i, :, :, 4]) and np.all(
                    x[i, :, :, 3] == x[i, :, :, 5]
                ):
                    self.depth_type = "log"
                    depth_linear = log_to_linear(x[i, :, :, 3:])
                    max_depth = linear_to_log(depth_linear + self.depth_delta_meters)
                    min_depth = linear_to_log(depth_linear - self.depth_delta_meters)
                    max_depth = np.transpose(np.minimum(1.0, max_depth), (2, 0, 1))
                    min_depth = np.transpose(np.maximum(0.0, min_depth), (2, 0, 1))
                else:
                    self.depth_type = "linear"
                    depth_linear = rgb_depth_to_linear(
                        x[i, :, :, 3], x[i, :, :, 4], x[i, :, :, 5]
                    )
                    max_depth = depth_linear + self.depth_delta_meters
                    min_depth = depth_linear - self.depth_delta_meters
                    max_depth = np.minimum(1000.0, max_depth)
                    min_depth = np.maximum(0.0, min_depth)

                self.max_depth = torch.tensor(
                    np.expand_dims(max_depth, axis=0),
                    dtype=torch.float32,
                    device=self.estimator.device,
                )
                self.min_depth = torch.tensor(
                    np.expand_dims(min_depth, axis=0),
                    dtype=torch.float32,
                    device=self.estimator.device,
                )
                self.depth_perturbation = torch.zeros(
                    1,
                    3,
                    x.shape[1],
                    x.shape[2],
                    requires_grad=True,
                    device=self.estimator.device,
                )

            # super().max_iter = maxITER
            patch, _ = super().generate(np.expand_dims(x[i], axis=0), y=[y_gt], model=model)

            # Patch image
            x_tensor = torch.tensor(np.expand_dims(x[i], axis=0)).to(
                self.estimator.device
            )
            patched_image = (
                self._random_overlay(
                    images=x_tensor, patch=self._patch, scale=None, mask=None
                )
                .detach()
                .cpu()
                .numpy()
            )
            patched_image = np.squeeze(patched_image, axis=0)

            # Embed patch into background
            patched_image[np.all(self.binarized_patch_mask == 0, axis=-1)] = x[i][
                np.all(self.binarized_patch_mask == 0, axis=-1)
            ]

            patched_image = np.clip(
                patched_image,
                self.estimator.clip_values[0],
                self.estimator.clip_values[1],
            )

            attacked_images.append(patched_image)

        return np.array(attacked_images)
