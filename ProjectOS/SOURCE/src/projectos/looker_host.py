from __future__ import annotations
import argparse,json,subprocess,sys
from pathlib import Path
from projectos.acceptance.authority import detect_host_session
from projectos.errors import ProjectOSError,ValidationError
from projectos.looker.collector import LookerCollector
from projectos.looker.evidence import verify_intake_archive
from projectos.looker.model import LookerIntake
from projectos.looker.policy import validate_collector_environment

class Executor:
    def run(self,argv,timeout_seconds,working_directory):
        try:
            value=subprocess.run(list(argv),cwd=working_directory,shell=False,capture_output=True,text=True,timeout=timeout_seconds,check=False)
            return type("Result",(),{"returncode":value.returncode,"stdout":value.stdout[:2048],"stderr":value.stderr[:2048],"timed_out":False})()
        except subprocess.TimeoutExpired:
            return type("Result",(),{"returncode":-1,"stdout":"","stderr":"","timed_out":True})()
def _intake(path):
    try: value=json.loads(Path(path).read_text())
    except (OSError,json.JSONDecodeError) as exc: raise ValidationError("Looker intake is unavailable or invalid") from exc
    return LookerIntake.from_mapping(value)
def parser():
    root=argparse.ArgumentParser(prog="python -m projectos.looker_host"); commands=root.add_subparsers(dest="command",required=True)
    for name in ("preflight","collect","recover"):
        item=commands.add_parser(name); item.add_argument("--intake",required=True,type=Path)
        if name=="collect": item.add_argument("--archive",required=True,type=Path); item.add_argument("--wheel-sha256",required=True)
    verify=commands.add_parser("verify"); verify.add_argument("--archive",required=True,type=Path)
    return root
def main(argv=None):
    try:
        args=parser().parse_args(argv)
        if args.command=="verify": data=verify_intake_archive(args.archive); result={"sha256":data.sha256,"size":data.size}
        else:
            intake=_intake(args.intake); session=detect_host_session()
            if args.command=="preflight": paths=validate_collector_environment(intake,session); result={"host_family":intake.host_family.value,"ready":True}
            elif args.command=="recover": LookerCollector().recover(intake,session); result={"recovered":True}
            else: result=LookerCollector().collect(intake,session,Executor(),args.archive,args.wheel_sha256).__dict__; result["output_path"]="[LOCAL]"
        print(json.dumps({"data":result,"errors":[],"ok":True},sort_keys=True,separators=(",",":"))); return 0
    except (ProjectOSError,ValidationError,ValueError) as exc:
        print(json.dumps({"data":{},"errors":[{"code":type(exc).__name__.upper(),"message":"Looker host validation failed"}],"ok":False},sort_keys=True,separators=(",",":"))); return 2
if __name__=="__main__": sys.exit(main())
