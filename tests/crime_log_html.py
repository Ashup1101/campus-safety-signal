"""Synthetic crime log pages in the live page's markup. Every value here is made up."""

_INCIDENT = """
                      <tr role="row" class="case_date">
                         <td> <strong>Case Number</strong> </td>
                         <td> {case} </td>
                         <td> <strong>Date Reported</strong> </td>
                         <td>
                            {reported}
                            </td>
                      </tr>
                      <tr role="row">
                        <td role="columnheader"><strong>Date Time From</strong></td>
                        <td>
                            {start}
                        </td>
                        <td role="columnheader"><strong>Date Time To</strong></td>
                        <td>
                            {end}
                        </td>
                    </tr>
                    <tr role="row">
                        <td role="columnheader"><strong>Location</strong></td>
                        <td>
                            {location}                        </td>
                        <td role="columnheader"><strong>Crime Description</strong></td>
                        <td>
                            {offense}                        </td>
                    </tr>
                    <tr role="row">
                        <td role="columnheader"><strong>Disposition</strong></td>
                        <td>
                            {disposition}                        </td>
                        <td role="presentation"></td>
                        <td role="presentation"></td>
                    </tr>"""

NO_CRIMES = (
    '<tr colspan="4" style="text-align:center" role="row"><td><strong>'
    "There are no crimes to report for the date range above.</strong></td></tr>"
)


def incident(
    case: str = "900001",
    reported: str = "10/25/2026",
    start: str = "10/24/2026 22:00:00",
    end: str = "10/24/2026 23:30:00",
    location: str = "SAMPLE HALL",
    offense: str = "THEFT FROM BUILDING LESS THAN $750",
    disposition: str = "OPEN CASE",
) -> str:
    return _INCIDENT.format(
        case=case,
        reported=reported,
        start=start,
        end=end,
        location=location,
        offense=offense,
        disposition=disposition,
    )


def section(
    campus: str, rows: str, window: str = "08/26/2026 - 10/25/2026", closed: bool = True
) -> str:
    return (
        f"<div style='text-align:center'><h2>Daily Crime & Fire Log for the IU {campus} Campus"
        f"</h2><h3><strong>{window}</strong></h3></div><br/>"
        '<table aria-labelledby="table-crime-info" class="mobile-labels crime-daily-log"'
        ' role="grid"><caption id="table-crime-info" class="visually-hidden">'
        f"Crime & Fire Log for the IU {campus} Campus</caption>{rows}"
        + ("</table>" if closed else "")
    )


def page(*sections: str) -> str:
    # The live page has a campus-name h3 in its nav before any table.
    return f"<html><body><h3>Bloomington</h3>{''.join(sections)}</body></html>"
