from __future__ import annotations
import hashlib, json, stat, sys, tempfile, unittest, warnings, zipfile
from pathlib import Path
from tests.helpers import REPO_ROOT
if str(REPO_ROOT / "src") not in sys.path: sys.path.insert(0, str(REPO_ROOT / "src"))
from projectos.errors import ValidationError


class LookerEvidenceTests(unittest.TestCase):
    def sections(self):
        return {name: {"format": name, "items": []} for name in ("repository", "looker-assets", "looker-relationships", "legacy-tracker", "automation", "validation", "credential-references", "findings")}

    def test_archive_has_exact_canonical_members_and_hashes(self):
        from projectos.looker.evidence import EVIDENCE_MEMBERS, LookerEvidenceBuilder, verify_intake_archive
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)/"evidence.zip"
            built=LookerEvidenceBuilder().build("source-machine-01","macos","run-01","1"*64,"2"*64,"3"*64,self.sections(),output)
            verified=verify_intake_archive(output)
            self.assertEqual(set(EVIDENCE_MEMBERS), set(verified.members))
            self.assertEqual(built.sha256, verified.sha256)

    def test_verifier_rejects_corruption_traversal_duplicate_symlink_extra_and_private_data(self):
        from projectos.looker.evidence import LookerEvidenceBuilder, verify_intake_archive
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); good=root/"good.zip"
            LookerEvidenceBuilder().build("source-machine-01","macos","run-01","1"*64,"2"*64,"3"*64,self.sections(),good)
            for name, mutate in {
                "extra": lambda z: z.writestr("extra.json", b"{}"),
                "traversal": lambda z: z.writestr("../bad.json", b"{}"),
                "private": lambda z: z.writestr("findings.json", b'{"email":"owner@example.com"}\n'),
                "symlink": lambda z: z.writestr(self.symlink_info("link"), b"target"),
            }.items():
                target=root/f"{name}.zip"; target.write_bytes(good.read_bytes())
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    with zipfile.ZipFile(target,"a") as archive: mutate(archive)
                with self.assertRaises(ValidationError): verify_intake_archive(target)

    def test_verifier_rejects_unknown_manifest_field_with_valid_checksums(self):
        from projectos.looker.evidence import LookerEvidenceBuilder, _info, verify_intake_archive
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); good=root/"good.zip"; changed=root/"changed.zip"
            LookerEvidenceBuilder().build("source-machine-01","macos","run-01","1"*64,"2"*64,"3"*64,self.sections(),good)
            with zipfile.ZipFile(good) as archive: content={name:archive.read(name) for name in archive.namelist()}
            manifest=json.loads(content["intake-manifest.json"]); manifest["unexpected_authority"]="accepted"
            content["intake-manifest.json"]=(json.dumps(manifest,sort_keys=True,separators=(",",":"))+"\n").encode()
            names=sorted(set(content)-{"SHA256SUMS.txt"})
            content["SHA256SUMS.txt"]="".join(f"{hashlib.sha256(content[name]).hexdigest()}  {name}\n" for name in names).encode()
            with zipfile.ZipFile(changed,"w") as archive:
                for name in sorted(content): archive.writestr(_info(name),content[name])
            with self.assertRaisesRegex(ValidationError,"manifest"):
                verify_intake_archive(changed)

    @staticmethod
    def symlink_info(name):
        info=zipfile.ZipInfo(name); info.external_attr=(stat.S_IFLNK|0o777)<<16
        return info
