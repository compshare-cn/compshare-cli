"""Public CompShare API actions covered by the CLI."""

INSTANCE_ACTIONS = frozenset(
    {
        "CheckCompShareNetOptimizer",
        "CheckCompShareResourceCapacity",
        "CreateCompShareInstance",
        "DeleteCompShareStopScheduler",
        "DescribeAvailableCompShareInstanceTypes",
        "DescribeCompShareInstance",
        "DescribeCompShareMachineTypeFamilies",
        "DescribeCompShareSoftwarePort",
        "DescribeCompShareSupportZone",
        "DescribeModelRepositoryModels",
        "GetCompShareInstanceMonitor",
        "GetCompShareInstancePrice",
        "GetCompShareInstanceUpgradePrice",
        "GetCompShareInstanceUserPrice",
        "GetCompShareRefundPrice",
        "GetSoftwareURL",
        "ModifyCompShareInstanceName",
        "RebootCompShareInstance",
        "ReinstallCompShareInstance",
        "ResetCompShareInstancePassword",
        "ResizeCompShareInstance",
        "StartCompShareInstance",
        "StopCompShareInstance",
        "SwitchChargeType",
        "TerminateCompShareInstance",
        "UpdateCompShareInstancePorts",
        "UpdateCompShareStopScheduler",
    }
)

IMAGE_ACTIONS = frozenset(
    {
        "CreateCompShareImageFavorite",
        "CreateCompShareCustomImage",
        "DeleteCompShareImageFavorite",
        "DescribeCommunityImages",
        "DescribeCompShareCustomImages",
        "DescribeCompShareImages",
        "DescribeCompShareImageShareAccounts",
        "DescribeCompShareImageTags",
        "DescribeCompShareSharingImages",
        "DescribeSelfCommunityImages",
        "DescribeUserCommunityImages",
        "GetCompShareImageCreateProgress",
        "ModifyCompShareImageShareAccount",
        "PublishCompShareImage",
        "TerminateCompShareCustomImage",
        "UpdateCompShareImage",
    }
)

STORAGE_ACTIONS = frozenset(
    {
        "AttachCompshareDisk",
        "AttachUS3",
        "CreateAndAttachCompshareDisk",
        "DeleteCompshareDisk",
        "DescribeCompshareDisk",
        "DetachCompshareDisk",
        "GetCompShareAttachedDiskUpgradePrice",
        "ResizeCompShareDisk",
    }
)

TEAM_ACTIONS = frozenset(
    {
        "CreateCompShareTeam",
        "CreateCompShareTeamRelation",
        "DeleteCompShareTeam",
        "DescribeTeamMemberOrder",
        "DescribeTeamMemberOrderCount",
        "DescribeTeamMemberUnpaidOrder",
        "DescribeTeamMemberUnpaidOrderCount",
        "DownloadTeamOrder",
        "GetCompShareTeamInfo",
        "ListCompShareTeam",
        "ListCompShareTeamInvite",
        "ListCompShareTeamJoined",
        "ListCompShareTeamOperateLog",
        "ListMemberProductType",
        "SetCompShareTeamAmount",
        "SetCompShareTeamRelation",
        "UpdateCompShareTeam",
    }
)

BANDWIDTH_ACTIONS = frozenset(
    {
        "CreateCompShareShareBandwidth",
        "DeleteCompShareShareBandwidth",
        "DescribeCompShareShareBandwidth",
        "GetCompShareShareBandwidthPrice",
        "GetCompShareShareBandwidthRefundPrice",
        "GetCompShareShareBandwidthUpgradePrice",
        "ModifyCompShareShareBandwidth",
        "SwitchCompShareEIPShareBandwidth",
    }
)

PUBLIC_ACTIONS = (
    INSTANCE_ACTIONS | IMAGE_ACTIONS | STORAGE_ACTIONS | TEAM_ACTIONS | BANDWIDTH_ACTIONS
)

# No unavailable API actions are currently exposed as placeholders.
COMING_SOON_ACTIONS = frozenset()

# Documented publicly but unavailable in the production API.
UNAVAILABLE_ACTIONS = frozenset(
    {
        "AddFavoriteImage",
        "DescribeFavoriteImages",
        "GetCompShareInstanceMonitor",
        "GetSoftwareURL",
        "RemoveFavoriteImage",
    }
)
