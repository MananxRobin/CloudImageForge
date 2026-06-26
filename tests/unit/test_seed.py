from cloudimageforge.apt import default_cloud_sources, guest_apt_path
from cloudimageforge.releases import get_release
from cloudimageforge.seed import MARKER_FAIL, MARKER_OK, cloud_init_meta_data, cloud_init_user_data


def test_guest_apt_path_jammy_list_vs_noble_deb822():
    assert guest_apt_path("jammy") == "/etc/apt/sources.list"
    assert guest_apt_path(get_release("noble")) == "/etc/apt/sources.list.d/ubuntu.sources"


def test_cloud_init_user_data_runs_apt_update_and_marks_result():
    sources = default_cloud_sources("jammy").render()
    user_data = cloud_init_user_data("jammy", sources)
    assert user_data.startswith("#cloud-config")
    assert "/etc/apt/sources.list" in user_data
    assert "/etc/ciforge/apt-sources" in user_data
    assert "apt-get update" in user_data
    assert "preserve_sources_list: true" in user_data
    assert MARKER_OK in user_data
    assert MARKER_FAIL in user_data
    assert "archive.ubuntu.com" in user_data
    assert "poweroff" in user_data
    assert "growpart:" in user_data
    assert "resize_rootfs: true" in user_data


def test_cloud_init_noble_clears_legacy_sources_list():
    sources = default_cloud_sources("noble").render()
    user_data = cloud_init_user_data("noble", sources)
    assert "/etc/apt/sources.list.d/ubuntu.sources" in user_data
    assert "printf '' > /etc/apt/sources.list" in user_data
    assert "find /etc/apt/sources.list.d -type f -delete" in user_data


def test_meta_data_has_instance_id():
    meta = cloud_init_meta_data("ciforge-jammy")
    assert "instance-id: ciforge-jammy" in meta
    assert "local-hostname: ciforge-jammy" in meta
