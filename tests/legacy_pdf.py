"""Minimal one-page text PDFs and synthetic legacy crime log text. Every value is made up."""


def make_pdf(lines: list[str]) -> bytes:
    def escape(text: str) -> str:
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    shown = " ".join(f"({escape(line)}) Tj T*" for line in lines)
    content = f"BT /F1 10 Tf 12 TL 40 760 Td {shown} ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R"
        " /Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{offset:010d} 00000 n \n" for offset in offsets).encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return out


REPORT = [
    "Indiana University, Bloomington",
    "Police Department",
    "daily crime log report",
    "from 02/16/2016 00:00 to 02/16/2016 23:59",
    "date reported: 02/16/16 - TUE at 13:13 report #: 900445",
    "general location: SAMPLE HALL - On Campus",
    "date occurred from: 02/12/16 - FRI at 17:00",
    "date occurred to: 02/16/16 - TUE at 13:00",
    "incident/offenses: VANDALISM, MISCHIEF",
    "disposition: OPEN CASE",
    "modified date: 02/17/16 - WED at 17:18",
    "date reported: 02/16/16 - TUE at 15:19 cad event #: 16-02-16-000123",
    "incident: SUSPICIOUS ACTIVITY",
    "location: SAMPLE LOT - Off Campus",
    "final incident: THEFT FROM",
    "BUILDING",
    "disposition: REPORT FILED",
]

# Layout-mode rows of the 2011-2013 form, with a wrapped location and disposition, a CAD event
# without a report number, and the page footer split over lines as pypdf sometimes splits it.
CAD = [
    "Student Right To Know CAD Daily Log",
    "From Feb 04, 2013 00:00 to Feb 04, 2013 23:59.",
    "Indiana University, Bloomington",
    "Police Department",
    "Date Reported: 02/04/13 - MON at 02:36 Location : 400 BLK N SAMPLE Event #: 13-02-04-000018",
    "Date and Time Occurred From - Occurred To 02/03/13 - SUN at 00:00 - 02/04/13 - MON at 03:00",
    "Incident : SEX OFFENSE/FORCIBLE - RAPE BY FORCE Report #: 900403",
    "Disposition: ACTIVE.",
    "Date Reported: 02/04/13 - MON at 12:01 Location : SAMPLE MEMORIAL Event #: 13-02-04-000041",
    "UNION",
    "Date and Time Occurred From - Occurred To",
    "Incident : DRUNKENNESS - PUBLIC INTOXICATION Report #:",
    "Disposition: FAILED TO",
    "LOCATE",
    "2 Incidents Listed.",
    "1 Page No. 1:23:45PM 2/4/201",
    "3",
    "Print Date and Time at",
]
