"""Public CompShare API actions covered by the first CLI release."""

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
        "AddFavoriteImage",
        "CreateCompShareCustomImage",
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
        "RemoveFavoriteImage",
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

PUBLIC_ACTIONS = INSTANCE_ACTIONS | IMAGE_ACTIONS | STORAGE_ACTIONS | TEAM_ACTIONS

# Public API actions intentionally exposed as CLI placeholders until their
# production request contract is ready.
COMING_SOON_ACTIONS = frozenset({"GetCompShareInstanceMonitor"})

# Documented publicly but unavailable in the production API (RetCode 161).
UNAVAILABLE_ACTIONS = frozenset({"DescribeFavoriteImages"})
