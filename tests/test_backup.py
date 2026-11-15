import sqlite3
import pytest
from deploy.backup_sqlite import backup


def test_consistent_backup_and_no_overwrite(tmp_path):
    source=tmp_path/"data.sqlite3"
    target=tmp_path/"backup.sqlite3"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE sample(value TEXT)")
        db.execute("INSERT INTO sample VALUES('preserved')")
    backup(source,target)
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT value FROM sample").fetchone()[0]=="preserved"
        assert db.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
    with pytest.raises(FileExistsError):
        backup(source,target)
    with pytest.raises(ValueError):
        backup(source,source)
    with pytest.raises(ValueError):
        backup(tmp_path/"missing",tmp_path/"new")
