_base_ = '../_base_/default_runtime.py'
dataset_info = '../_base_/datasets/coco.py'

data_root = '/home/houbowei/subcoco/'
# dataset_type = 'YOLOv5CocoDataset'
dataset_type = 'YOLOv5PoseCocoDataset'

img_scale = (640, 640)  # width, height
deepen_factor = 0.33
widen_factor = 0.5

save_epoch_intervals = 1
train_batch_size_per_gpu = 8
# NOTE: for debugging set to 0
train_num_workers = 8
val_batch_size_per_gpu = 1
# NOTE: for debugging set to 0
val_num_workers = 8

max_epochs = 100  # NOTE: for debug
num_last_epochs = 15

# model settings
model = dict(
    type='YOLODetector',
    init_cfg=dict(
        type='Kaiming',
        layer='Conv2d',
        a=2.23606797749979,  # math.sqrt(5)
        distribution='uniform',
        mode='fan_in',
        nonlinearity='leaky_relu'),
    # TODO: Waiting for mmengine support
    use_syncbn=False,
    data_preprocessor=dict(
        type='mmdet.DetDataPreprocessor',
        pad_size_divisor=32,
        batch_augments=[
            dict(
                type='mmdet.BatchSyncRandomResize',
                random_size_range=(480, 800),
                size_divisor=32,
                interval=10)
        ]),
    backbone=dict(
        type='YOLOXCSPDarknet',
        deepen_factor=deepen_factor,
        widen_factor=widen_factor,
        out_indices=(2, 3, 4),
        spp_kernal_sizes=(5, 9, 13),
        norm_cfg=dict(type='BN', momentum=0.03, eps=0.001),
        act_cfg=dict(type='SiLU', inplace=True),
    ),
    neck=dict(
        type='YOLOXPAFPN',
        deepen_factor=deepen_factor,
        widen_factor=widen_factor,
        in_channels=[256, 512, 1024],
        out_channels=256,
        norm_cfg=dict(type='BN', momentum=0.03, eps=0.001),
        act_cfg=dict(type='SiLU', inplace=True)),
    bbox_head=dict(
        type='YOLOXKptHead',
        head_module=dict(
            type='YOLOXKptHeadModule',
            num_classes=1,
            num_keypoints=17,
            in_channels=256,
            feat_channels=256,
            kpt_stacked_convs=4,
            widen_factor=widen_factor,
            stacked_convs=2,
            featmap_strides=(8, 16, 32),
            use_depthwise=False,
            norm_cfg=dict(type='BN', momentum=0.03, eps=0.001),
            act_cfg=dict(type='SiLU', inplace=True),
        ),
        kpt_coder=dict(type='YOLOXKptCoder'),
        loss_cls=dict(
            type='mmdet.CrossEntropyLoss',
            use_sigmoid=True,
            reduction='sum',
            loss_weight=1.0),
        loss_bbox=dict(
            type='mmdet.IoULoss',
            mode='square',
            eps=1e-16,
            reduction='sum',
            loss_weight=5.0),
        loss_obj=dict(
            type='mmdet.CrossEntropyLoss',
            use_sigmoid=True,
            reduction='sum',
            loss_weight=1.0),
        loss_bbox_aux=dict(
            type='mmdet.L1Loss', reduction='sum', loss_weight=1.0),
        loss_kpt=dict(type='OksLoss', dataset_info=dataset_info,loss_weight=70, loss_type='oks_yolox')),
    train_cfg=dict(
        assigner=dict(
            type='mmdet.SimOTAAssigner',
            center_radius=2.5,
            iou_calculator=dict(type='mmdet.BboxOverlaps2D'))),
    test_cfg=dict(
        yolox_style=True,  # better
        multi_label=True,  # 40.5 -> 40.7
        score_thr=0.001,
        max_per_img=300,
        nms=dict(type='nms', iou_threshold=0.65)))

# codec = dict(type="mmpose.RegressionLabel")
pre_transform = [
    dict(type='LoadImageFromFile', file_client_args=_base_.file_client_args),
    dict(type='LoadAnnotations', with_bbox=True, with_keypoints=True)
]

train_pipeline_stage1 = [
    *pre_transform,
    dict(type='YOLOPoseResize', scale=img_scale, keep_ratio=True),
    dict(
        type='mmdet.Pad',
        pad_to_square=True,
        # If the image is three-channel, the pad value needs
        # to be set separately for each channel.
        pad_val=dict(img=(114.0, 114.0, 114.0))),
    # dict(
    #     type='MosaicKeypoints',
    #     img_scale=img_scale,
    #     pad_val=114.0,
    #     pre_transform=pre_transform),
    # dict(
    #     # type='mmdet.RandomAffine',
    #     type='YOLOPoseRandomAffine',
    #     scaling_ratio_range=(0.75, 1),
    #     max_translate_ratio=0.0,
    #     max_shear_degree=2.0,
    #     # img_scale is (width, height)
    #     border=(-img_scale[0] // 2, -img_scale[1] // 2)),
    # dict(
    #     type='YOLOXMixUpPose',
    #     prob=0.0,
    #     flip_ratio=1.0,
    #     img_scale=img_scale,
    #     ratio_range=(0.8, 1.6),
    #     pad_val=114.0,
    #     pre_transform=pre_transform),
    # dict(type='mmdet.YOLOXHSVRandomAug'),
    # dict(type='YOLOPoseRandomFlip', prob=0.5),
    dict(
        type='YOLOPoseFilterAnnotations',
        min_gt_bbox_wh=(1, 1),
        keep_empty=False,
        by_keypoints=True,
        min_keypoints=1),
    dict(
        type='YOLOPosePackInputs',
        meta_keys=('img_id', 'img_path', 'ori_shape', 'img_shape'))
]

train_pipeline_stage2 = [
    *pre_transform,
    dict(type='YOLOPoseResize', scale=img_scale, keep_ratio=True),
    dict(
        type='mmdet.Pad',
        pad_to_square=True,
        # If the image is three-channel, the pad value needs
        # to be set separately for each channel.
        pad_val=dict(img=(114.0, 114.0, 114.0))),
    # dict(type='mmdet.YOLOXHSVRandomAug'),
    # dict(type='YOLOPoseRandomFlip', prob=0.5),
    dict(
        type='YOLOPoseFilterAnnotations',
        min_gt_bbox_wh=(1, 1),
        keep_empty=False,
        by_keypoints=True,
        min_keypoints=1),
    dict(type='YOLOPosePackInputs')
]

train_dataloader = dict(
    batch_size=train_batch_size_per_gpu,
    num_workers=train_num_workers,
    persistent_workers=False,  # NOTE: for debugging
    pin_memory=False,  # NOTE: for debugging
    sampler=dict(type='DefaultSampler', shuffle=True),
    dataset=dict(
        type=dataset_type,
        data_root=data_root,
        metainfo=dataset_info,
        ann_file='annotations/person_keypoints_train2017.json',
        data_prefix=dict(img='train2017/'),
        filter_cfg=dict(filter_empty_gt=False, min_size=32),
        pipeline=train_pipeline_stage1))

test_pipeline = [
    *pre_transform,
    # dict(type='LoadImageFromFile', file_client_args=_base_.file_client_args),
    dict(type='YOLOPoseResize', scale=img_scale, keep_ratio=True),
    dict(
        type='mmdet.Pad',
        pad_to_square=True,
        pad_val=dict(img=(114.0, 114.0, 114.0))),
     dict(
        type='YOLOPoseFilterAnnotations',
        min_gt_bbox_wh=(1, 1),
        keep_empty=False,
        by_keypoints=True,
        min_keypoints=1),
    dict(
        type='YOLOPosePackInputs',
        meta_keys=('img_id', 'img_path', 'ori_shape', 'img_shape',
                   'scale_factor'))
]
# test_pipeline = train_pipeline_stage2

val_dataloader = dict(
    batch_size=val_batch_size_per_gpu,
    num_workers=val_num_workers,
    persistent_workers=False,  # NOTE: for debugging
    pin_memory=False,  # NOTE: for debugging
    drop_last=False,
    sampler=dict(type='DefaultSampler', shuffle=False),
    dataset=dict(
        type=dataset_type,
        data_root=data_root,
        metainfo=dataset_info,
        ann_file='annotations/person_keypoints_val2017.json',
        data_prefix=dict(img='val2017/'),
        test_mode=True,
        pipeline=test_pipeline,
    ))
test_dataloader = val_dataloader

# Reduce evaluation time
val_evaluator = [
    dict(
        type='mmdet.CocoMetric',
        proposal_nums=(100, 1, 10),
        ann_file=data_root + 'annotations/person_keypoints_val2017.json',
        metric=['bbox']),
    dict(
        type='CocoMetric',
        ann_file=data_root + 'annotations/person_keypoints_val2017.json')
]

test_evaluator = val_evaluator

# optimizer
# default 8 gpu
# NOTE: clip grad is necessary for training.
base_lr = 0.01
optim_wrapper = dict(
    type='OptimWrapper',
    optimizer=dict(
        type='SGD', lr=base_lr, momentum=0.9, weight_decay=5e-4,
        nesterov=True))
    # paramwise_cfg=dict(norm_decay_mult=0., bias_decay_mult=0.),
    # clip_grad=dict(max_norm=35, norm_type=2))

# learning rate
param_scheduler = [
    dict(
        # use quadratic formula to warm up 5 epochs
        # and lr is updated by iteration
        # TODO: fix default scope in get function
        type='mmdet.QuadraticWarmupLR',
        by_epoch=True,
        begin=0,
        end=5,
        convert_to_iter_based=True),
    dict(
        # use cosine lr from 5 to 285 epoch
        type='CosineAnnealingLR',
        eta_min=base_lr * 0.05,
        begin=5,
        T_max=max_epochs - num_last_epochs,
        end=max_epochs - num_last_epochs,
        by_epoch=True,
        convert_to_iter_based=True),
    dict(
        # use fixed lr during last 15 epochs
        type='ConstantLR',
        by_epoch=True,
        factor=1,
        begin=max_epochs - num_last_epochs,
        end=max_epochs,
    )
]

default_hooks = dict(
    checkpoint=dict(
        type='CheckpointHook', interval=1, max_keep_ckpts=3, save_best=['auto'],
        greater_keys=['coco/AP', 'coco/bbox_mAP'])
    )

custom_hooks = [
    dict(
        type='YOLOXModeSwitchHook',
        num_last_epochs=num_last_epochs,
        new_train_pipeline=train_pipeline_stage2,
        priority=48),
    dict(type='mmdet.SyncNormHook', priority=48),
    dict(
        type='EMAHook',
        ema_type='ExpMomentumEMA',
        momentum=0.0001,
        update_buffers=True,
        strict_load=False,
        priority=49)
]

train_cfg = dict(
    type='EpochBasedTrainLoop',
    max_epochs=max_epochs,
    val_interval=save_epoch_intervals,
    dynamic_intervals=[(max_epochs - num_last_epochs, 1)])

auto_scale_lr = dict(base_batch_size=64)
val_cfg = dict(type='ValLoop')
test_cfg = dict(type='TestLoop')

# 17 keypoints
keypoint_colors = [(255, 0, 0), (255, 85, 0), (255, 170, 0), (255, 0, 85),
                   (255, 0, 170), (0, 255, 0), (85, 255, 0), (170, 255, 0),
                   (0, 255, 85), (0, 255, 170), (0, 0, 255), (85, 0, 255),
                   (170, 0, 255), (0, 85, 255), (0, 170, 255), (255, 255, 0),
                   (255, 255, 85)]

skeleton_links = [(0, 1), (0, 2), (1, 3), (2, 4), (0, 5), (0, 6), (5, 7),
                  (7, 9), (6, 8), (8, 10), (5, 6), (5, 11), (6, 12), (11, 12),
                  (11, 13), (13, 15), (12, 14), (14, 16)]

# 18 links
skeleton_links_colors = [
    (255, 0, 0), (255, 85, 0), (255, 170, 0), (255, 0, 85), (255, 0, 170),
    (0, 255, 0), (85, 255, 0), (170, 255, 0), (0, 255, 85), (0, 255, 170),
    (0, 0, 255), (85, 0, 255), (170, 0, 255), (0, 85, 255), (0, 170, 255),
    (255, 255, 0), (255, 255, 85), (255, 0, 255)
]

vis_backends = [dict(type='LocalVisBackend'), dict(type='WandbVisBackend')]
visualizer = dict(
    # type='mmdet.DetLocalVisualizer',
    type='mmpose.PoseLocalVisualizer',
    vis_backends=vis_backends,
    kpt_color=keypoint_colors,
    skeleton=skeleton_links,
    link_color=skeleton_links_colors,
    name='visualizer')
seed=0
load_from="/home/houbowei/yolox-pose/YOLOX_outputs/kpt_anno_separate_head/best_ckpt_mmyolo.pth"