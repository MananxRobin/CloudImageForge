"""Errors raised by CloudImageForge."""


class CloudImageForgeError(Exception):
    """Base error for the pipeline."""


class UnsupportedReleaseError(CloudImageForgeError):
    """The requested Ubuntu release is not a supported cloud target."""


class BrokenAptSourceError(CloudImageForgeError):
    """An apt source is malformed, mismatched, or would fail on a clean image."""


class ArchiveAPIError(CloudImageForgeError):
    """Ubuntu Archive / Launchpad API request failed."""


class PackageBuildError(CloudImageForgeError):
    """dpkg-deb, sbuild, or pbuilder could not produce a package."""


class DependencyResolutionError(CloudImageForgeError):
    """A binary dependency could not be resolved against an apt index."""


class StagingRequiredError(CloudImageForgeError):
    """A dependency resolved on the host but not on a clean cloud image."""


class PublishBlockedError(CloudImageForgeError):
    """Direct publish refused; staging fallback check has not passed."""


class InteropError(CloudImageForgeError):
    """The package is not installable across the requested Ubuntu releases."""


class BootCheckError(CloudImageForgeError):
    """LXD/QEMU (or simulated) boot check failed."""
