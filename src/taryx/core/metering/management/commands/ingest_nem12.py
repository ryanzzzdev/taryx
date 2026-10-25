from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from taryx.core.metering.ingestion import ingest_nem12_content


class Command(BaseCommand):
    help = "Ingest a NEM12 (MDFF interval data) file into versioned metering history."

    def add_arguments(self, parser):
        parser.add_argument("paths", nargs="+", type=str)

    def handle(self, *args, **options):
        for raw_path in options["paths"]:
            path = Path(raw_path)
            if not path.is_file():
                raise CommandError(f"not a file: {path}")
            result = ingest_nem12_content(path.read_bytes(), path.name)
            batch = result.batch
            line = f"{path.name}: {batch.status}"
            if batch.status == "rejected":
                line += f" ({batch.error_code}: {batch.error_detail})"
            elif batch.status == "published":
                line += (
                    f" ({batch.record_count} intervals, "
                    f"{batch.accepted_count} selected, "
                    f"{batch.quarantined_count} quarantined)"
                )
            self.stdout.write(line)
