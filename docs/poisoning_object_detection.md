# Object Detection Poisoning

## Threat Model
[BadDet](https://arxiv.org/pdf/2205.14497.pdf) Object Detection Poisoning comprises 4 separate dirty-label object detection attacks.  

### Regional Misclassification Attack (RMA)

In a fraction of training images, a backdoor trigger is added within the bounding box of all objects from the source class (optionally, all classes), and the associated labels are changed to the target class.  At test time, adding the trigger to a bounding box induces misclassification for that object.

### Global Misclassification Attack (GMA)

A backdoor trigger is added to a fraction of the training images, and all labels in those images are changed to the target class.  At test time, adding the trigger to an image should result in all objects in that image being classified as the target class.

### Object Disappearance Attack (ODA)

In a fraction of training images, a backdoor trigger is inserted within the bounding box of all source class objects, and their bounding boxes and labels are deleted.  At test time, placing the trigger in the bounding box of a source class object should cause it not to be detected by the model.

### Object Generation Attack (OGA)

A backdoor trigger is added to a random spot in a fraction of the training image, and a fake bounding box is added with a target label.  At test time, inserting the trigger causes the hallucination of a target object.




## Configuration Files

The configuration files for each attack are similar.  The source and target class requirements are as follows:
- RMA - source and target class; source can also be None and the attack will poison all classes.
- GMA - target class.
- ODA - source class.
- OGA - target class.

In addition, OGA requires the specification of a bbox size for the generated bounding box.
This is set under ```"attack"/"kwargs"/"backdoor_kwargs"``` as ```"bbox_height"``` and ```"bbox_width"```.


## Metrics

The metrics described in the paper are based on mean average precision.  Specifically, we measure the average precision (per-class and mean) on benign data as a base reference.  Then we measure the average precision on adversarial predictions both against the clean labels and the poisoned labels.  This gives insight into the performance degredation due to the attack, as well as the attack's ability to force a specific outcome.  For full details, we refer to the [paper](https://arxiv.org/pdf/2205.14497.pdf).

Finally, each variant of the attack has its own Attack Success Rate:
- RMA - the percent of triggered source class objects that are classified as target.  If source class is None, it is the percent of non-target class objects that are classified as target.
- GMA - the percent of non-target objects that are classified as target.
- ODA - the percent of source class boxes with no overlapping prediction (that meets the IOU threshold).
- OGA - the percent of fake bounding boxes that the model predicts.

The fairness metrics, as currently defined, are not applicable.


## Additional Notes

The OD poisoning scenario code performs some dataset operations which may seem out of place.  The data is padded and resized for YOLOv3 and augmented for training.  Non-maximum suppression is applied to the model's predictions.  Finally, for RMA and ODA, bounding boxes that are too small to contain the trigger are removed; if an image has no other bounding boxes, that image is removed from the dataset.  

The ART PytorchYolo class will in a future day take over some of these operations, which will simplify the scenario code.