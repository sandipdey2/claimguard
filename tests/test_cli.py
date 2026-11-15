import json

from claimguard.cli import main


def test_cli_commands(capsys):
    assert main(["cases"]) == 0 and "MN25-45854" in capsys.readouterr().out
    assert main(["search", "cochlear implant", "-k", "1"]) == 0 and "[NCD-50.3" in capsys.readouterr().out
    assert main(["score", "MN25-44606"]) == 0 and 0 < json.loads(capsys.readouterr().out)["overturn_probability"] < 1
    assert main(["verify-snapshot"]) == 0 and '"ok": true' in capsys.readouterr().out
    assert main(["score", "XX00-0"]) == 1
