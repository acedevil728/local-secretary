"""명령줄 도구.

    python -m app serve                 # 서버 실행 (APP_ENV=dev|prod)
    python -m app token create 거실태블릿  # 기기 토큰 발급
    python -m app rebuild               # 노트에서 DB 다시 만들기
    python -m app reset-dev-data        # 개발 데이터(.dev-data)를 예시 데이터로 되돌리기
    python -m app eval --mode ollama    # 평가셋으로 추출 정확도 측정 (Phase 0)
    python -m app config                # 지금 적용되는 설정 보기(비밀은 가림)
    python -m app config --ports        # start/stop 스크립트용 KEY=VALUE (주소·포트)
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys

from .core.config import load_settings


def _utf8_console() -> None:
    # Windows 콘솔 기본값(cp949)에서도 한글이 깨지지 않게
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass


def cmd_serve(args) -> None:
    import uvicorn

    from .main import create_app

    s = load_settings()
    uvicorn.run(create_app(s), host=args.host or s.host, port=args.port or s.port, log_level="info")


def cmd_token(args) -> None:
    from .api.auth import TokenStore

    store = TokenStore(load_settings().data_dir / "tokens.json")
    if args.action == "create":
        token = store.create(args.name)
        print(f"'{args.name}' 토큰 (한 번만 보여요):\n{token}")
    elif args.action == "revoke":
        print("삭제함" if store.revoke(args.name) else "없음")
    else:
        for t in store.list():
            print(f"{t['name']}\t{t['created']}")


def cmd_rebuild(args) -> None:
    from .context import build_context

    s = load_settings()
    db = s.data_dir / "app.db"
    if args.full:
        for p in (db, db.with_name("app.db-wal"), db.with_name("app.db-shm")):
            p.unlink(missing_ok=True)
    ctx = build_context(s, threads=False)
    ctx.start()
    n = ctx.extraction.run_pending()
    print(f"다시 읽음: 사람 {len(ctx.people.ids())}명, 분석 {n}개 섹션")


def cmd_reset_dev(args) -> None:
    s = load_settings("dev")
    if not s.data_seed:
        sys.exit("DATA_SEED가 없어요")
    if s.data_dir.exists():
        shutil.rmtree(s.data_dir)
    print(f"{s.data_dir} 지움. 다음 실행 때 {s.data_seed}에서 다시 복사해요.")


def cmd_eval(args) -> None:
    from .extraction.evaluate import run_eval

    s = load_settings(overrides={"LLM_MODE": args.mode} if args.mode else None)
    ok = run_eval(s, verbose=args.verbose)
    sys.exit(0 if ok else 1)


SECRET_FIELDS = {"telegram_bot_token", "smtp_password"}


def cmd_config(args) -> None:
    from dataclasses import fields

    s = load_settings()
    if args.ports:
        # start/stop 스크립트가 읽는다. 형식을 바꾸면 scripts/*.ps1, *.sh 도 같이 고친다.
        for key, value in (
            ("APP_ENV", s.env),
            ("HOST", s.host),
            ("PORT", s.port),
            ("WEB_HOST", s.web_host),
            ("WEB_PORT", s.web_port),
        ):
            print(f"{key}={value}")
        return
    for f in fields(s):
        value = getattr(s, f.name)
        if f.name in SECRET_FIELDS and value:
            value = "****(설정됨)"
        print(f"{f.name:22} {value}")


def main(argv: list[str] | None = None) -> None:
    _utf8_console()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="local-secretary")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("serve")
    sp.add_argument("--host")
    sp.add_argument("--port", type=int)
    sp.set_defaults(fn=cmd_serve)

    tp = sub.add_parser("token")
    tp.add_argument("action", choices=["create", "revoke", "list"])
    tp.add_argument("name", nargs="?", default="device")
    tp.set_defaults(fn=cmd_token)

    rp = sub.add_parser("rebuild")
    rp.add_argument("--full", action="store_true", help="DB 파일을 지우고 처음부터")
    rp.set_defaults(fn=cmd_rebuild)

    dp = sub.add_parser("reset-dev-data")
    dp.set_defaults(fn=cmd_reset_dev)

    ep = sub.add_parser("eval")
    ep.add_argument("--mode", choices=["ollama", "rule", "fixture", "replay", "record"])
    ep.add_argument("-v", "--verbose", action="store_true")
    ep.set_defaults(fn=cmd_eval)

    cp = sub.add_parser("config")
    cp.add_argument("--ports", action="store_true", help="주소·포트만 KEY=VALUE로")
    cp.set_defaults(fn=cmd_config)

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
