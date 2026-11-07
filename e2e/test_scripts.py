"""scripts/*.sh с подставными docker/rclone/crontab/curl: проверяем логику скриптов без Docker и сервера."""
import gzip
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"), reason="нужен bash")


def stub(bindir: Path, name: str, body: str):
    p = bindir / name
    p.write_text("#!/usr/bin/env bash\n" + body)
    p.chmod(p.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def proj(tmp_path):
    """Копия папки салона: scripts/ + .env, и папка с подставными командами (пишут вызовы в calls.log)."""
    d = tmp_path / "salon-test"
    shutil.copytree(ROOT / "scripts", d / "scripts")
    (d / ".env").write_text("BOT_TOKEN=1:x\n")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "calls.log"
    # docker: pg_dump печатает «дамп», compose ps -q → id, inspect → состояние из $BOT_STATE
    stub(bindir, "docker", f'''echo "docker $*" >> "{log}"
case "$*" in
  *pg_dump*) echo "-- dump";;
  "compose ps -q bot") echo "abc123";;
  inspect*) echo "${{BOT_STATE:-healthy}}";;
  *"psql"*"-tAc"*) echo 7;;
  *"psql"*) cat >/dev/null;;
esac
[ -n "${{DOCKER_FAIL:-}}" ] && [[ "$*" == *"$DOCKER_FAIL"* ]] && exit 1
exit 0
''')
    stub(bindir, "rclone", f'echo "rclone $*" >> "{log}"\nexit ${{RCLONE_EXIT:-0}}\n')
    stub(bindir, "curl", f'echo "curl $*" >> "{log}"\n')
    cron = tmp_path / "crontab.txt"
    stub(bindir, "crontab", f'''if [ "$1" = "-l" ]; then [ -f "{cron}" ] && cat "{cron}" || exit 1
elif [ "$1" = "-" ]; then cat > "{cron}"; fi
''')
    return d, bindir, log, cron


def run(proj, script, *args, env=None, path_extra=True):
    d, bindir, log, _ = proj
    base_path = "/usr/bin:/bin"
    e = {"PATH": f"{bindir}:{base_path}" if path_extra else base_path, "HOME": str(d), **(env or {})}
    return subprocess.run(["bash", f"scripts/{script}", *args], cwd=d, env=e, capture_output=True, text=True)


def calls(proj):
    log = proj[2]
    return log.read_text() if log.exists() else ""


def test_backup_local_only(proj):
    r = run(proj, "backup.sh")
    assert r.returncode == 0, r.stderr
    files = list((proj[0] / "backups").glob("*.sql.gz"))
    assert len(files) == 1 and gzip.decompress(files[0].read_bytes()) == b"-- dump\n"
    assert not list((proj[0] / "backups").glob("*.part"))
    assert "rclone" not in calls(proj)


def test_backup_keeps_14(proj):
    b = proj[0] / "backups"
    b.mkdir()
    for i in range(20):
        f = b / f"old-{i:02d}.sql.gz"
        f.write_bytes(gzip.compress(b"x"))
        os.utime(f, (1_000_000 + i, 1_000_000 + i))
    assert run(proj, "backup.sh").returncode == 0
    assert len(list(b.glob("*.sql.gz"))) == 14


def test_backup_to_remote(proj):
    (proj[0] / ".env").write_text('BACKUP_REMOTE="s3remote:bucket/parik"\n')
    r = run(proj, "backup.sh")
    assert r.returncode == 0, r.stderr
    assert "rclone copy backups/salon-test-" in calls(proj) and "s3remote:bucket/parik/salon-test/" in calls(proj)


def test_backup_remote_without_rclone(proj):
    (proj[0] / ".env").write_text("BACKUP_REMOTE=s3remote:bucket\n")
    (proj[1] / "rclone").unlink()
    r = run(proj, "backup.sh")
    assert r.returncode == 3 and "rclone не установлен" in r.stderr
    assert list((proj[0] / "backups").glob("*.sql.gz"))  # локальная копия есть


def test_backup_remote_fails(proj):
    (proj[0] / ".env").write_text("BACKUP_REMOTE=s3remote:bucket\n")
    r = run(proj, "backup.sh", env={"RCLONE_EXIT": "1"})
    assert r.returncode == 3 and "не удалось выгрузить" in r.stderr


def test_backup_dump_fails_leaves_no_file(proj):
    r = run(proj, "backup.sh", env={"DOCKER_FAIL": "pg_dump"})
    assert r.returncode != 0
    assert not list((proj[0] / "backups").glob("*.sql.gz"))


def test_install_cron_idempotent(proj):
    d, _, _, cron = proj
    cron.write_text("0 1 * * * echo чужая задача\n")
    for _ in range(3):
        assert run(proj, "install-cron.sh").returncode == 0
    lines = cron.read_text().splitlines()
    assert lines.count("0 1 * * * echo чужая задача") == 1
    mine = [x for x in lines if f"# parik-bot:{d}" in x]
    assert len(mine) == 1 and mine[0].startswith("15 4 * * * ") and "scripts/backup.sh" in mine[0]

    (d / ".env").write_text("HEARTBEAT_URL=https://kuma.example/api/push/x\nDEMO_MODE=1\n")
    run(proj, "install-cron.sh")
    mine = [x for x in cron.read_text().splitlines() if f"# parik-bot:{d}" in x]
    assert len(mine) == 3 and any("heartbeat.sh" in x for x in mine) and any("reset-demo" in x for x in mine)

    assert run(proj, "install-cron.sh", "--remove").returncode == 0
    assert cron.read_text().splitlines() == ["0 1 * * * echo чужая задача"]


def test_heartbeat(proj):
    d = proj[0]
    assert run(proj, "heartbeat.sh").returncode == 1  # URL не задан
    (d / ".env").write_text("HEARTBEAT_URL=https://kuma.example/api/push/abc\n")
    r = run(proj, "heartbeat.sh")
    assert r.returncode == 0, r.stderr
    assert "curl -fsS -m 10 --retry 2 https://kuma.example/api/push/abc" in calls(proj)


@pytest.mark.parametrize("env,reason", [({"BOT_STATE": "unhealthy"}, "бот: unhealthy"),
                                        ({"DOCKER_FAIL": "/health"}, "API не отвечает")])
def test_heartbeat_silent_when_sick(proj, env, reason):
    (proj[0] / ".env").write_text("HEARTBEAT_URL=https://kuma.example/api/push/abc\n")
    r = run(proj, "heartbeat.sh", env=env)
    assert r.returncode == 2 and reason in r.stderr
    assert "curl" not in calls(proj)


def test_restore_test_flow(proj):
    b = proj[0] / "backups"
    assert run(proj, "restore-test.sh").returncode == 1  # бэкапов нет
    b.mkdir()
    (b / "x.sql.gz").write_bytes(b"not gzip")
    assert "повреждён" in run(proj, "restore-test.sh").stdout
    (b / "x.sql.gz").write_bytes(gzip.compress(b"select 1;"))
    r = run(proj, "restore-test.sh")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Клиентов:      7" in r.stdout and "OK: бэкап восстанавливается" in r.stdout
    log = calls(proj)
    assert "docker run -d --rm --name restore-test-salon-test-" in log and "docker rm -f restore-test-" in log
