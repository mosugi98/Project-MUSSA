from tools.packaging import build_exe


def test_the_build_command_ships_the_artwork_folder():
    cmd = build_exe.pyinstaller_command()
    assert "--add-data" in cmd
    spec = cmd[cmd.index("--add-data") + 1]
    source, _sep, dest = spec.rpartition(";") if ";" in spec else spec.rpartition(":")
    assert source.replace("\\", "/").endswith("src/cagsyntax/ui/assets")
    assert dest == "cagsyntax/ui/assets"
