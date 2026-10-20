import hashlib
import zipfile

import pytest

from focuslab import updater


def release_json(tag: str, *names: str) -> dict:
    return {
        "tag_name": tag,
        "html_url": f"https://github.com/{updater.REPO}/releases/tag/{tag}",
        "assets": [
            {"name": n, "browser_download_url": f"https://example.invalid/{n}"} for n in names
        ],
    }


def test_versions_compare_numerically_and_ignore_prefix_and_suffix():
    assert updater.parse_version("v0.10.0") == (0, 10, 0)
    assert updater.parse_version("1.2.3-rc1+build5") == (1, 2, 3)
    assert updater.is_newer(updater.Release("0.10.0", "", None, None), current="0.9.9")
    assert not updater.is_newer(updater.Release("0.1.0", "", None, None), current="0.1.0")


def test_release_picks_the_windows_package_and_its_checksum():
    name = updater.asset_name("0.2.0")
    release = updater.parse_release(release_json("v0.2.0", "notes.txt", name, f"{name}.sha256"))
    assert release.version == "0.2.0"
    assert release.zip_url.endswith(name)
    assert release.sha256_url.endswith(f"{name}.sha256")
    bare = updater.parse_release(release_json("v0.3.0"))
    assert bare.zip_url is None and bare.sha256_url is None


def package(tmp_path, version="0.2.0"):
    source = tmp_path / "pkg"
    (source / "FocusLab" / "_internal").mkdir(parents=True)
    (source / "FocusLab" / "FocusLab.exe").write_bytes(b"new exe")
    zip_path = tmp_path / updater.asset_name(version)
    with zipfile.ZipFile(zip_path, "w") as archive:
        for path in source.rglob("*"):
            archive.write(path, path.relative_to(source))
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    sha_path = tmp_path / f"{zip_path.name}.sha256"
    return zip_path, sha_path, digest


def test_download_verifies_the_published_sha256(tmp_path):
    zip_path, sha_path, digest = package(tmp_path)
    sha_path.write_text(f"{digest}  {zip_path.name}\n")
    release = updater.Release("0.2.0", "", zip_path.as_uri(), sha_path.as_uri())
    seen = []
    got = updater.download(release, tmp_path / "downloads", seen.append)
    assert got.read_bytes() == zip_path.read_bytes()
    assert seen[-1] == 100

    sha_path.write_text("0" * 64)
    with pytest.raises(ValueError, match="checksum mismatch"):
        updater.download(release, tmp_path / "bad")
    assert not any((tmp_path / "bad").iterdir())  # no partial or unverified file is kept


def test_download_requires_a_windows_package(tmp_path):
    with pytest.raises(ValueError):
        updater.download(updater.Release("0.2.0", "", None, None), tmp_path)


def test_stage_unpacks_next_to_the_install_folder(tmp_path):
    zip_path, _, _ = package(tmp_path)
    install = tmp_path / "apps" / "FocusLab"
    (install / "_internal").mkdir(parents=True)
    staged = updater.stage(zip_path, install)
    assert staged == install.with_name(".FocusLab-update")
    assert (staged / "FocusLab.exe").read_bytes() == b"new exe"
    assert sorted(p.name for p in install.parent.iterdir()) == [".FocusLab-update", "FocusLab"]


def test_stage_rejects_a_package_without_focuslab(tmp_path):
    zip_path = tmp_path / "other.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("readme.txt", "nothing here")
    install = tmp_path / "FocusLab"
    install.mkdir()
    with pytest.raises(ValueError):
        updater.stage(zip_path, install)


def test_swap_script_quotes_paths_and_restarts_the_exe(tmp_path):
    target = tmp_path / "it's" / "FocusLab"
    script = updater.swap_script(target.with_name(".FocusLab-update"), target, 4242)
    assert "Wait-Process -Id 4242" in script
    assert "it''s" in script  # single quotes are doubled inside PowerShell literals
    exe = str(target / "FocusLab.exe").replace("'", "''")
    assert f"$exe = '{exe}'" in script
    assert "Start-Process -FilePath $exe" in script


def test_source_checkouts_never_replace_themselves():
    assert not updater.can_self_update()
