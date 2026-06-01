from datetime import date

from app.services.apple_calendar import (
    _find_calendar_href,
    _parse_calendar_report,
)


SAMPLE_CALENDAR_LIST = """<?xml version="1.0" encoding="UTF-8"?>
<D:multistatus xmlns:D="DAV:">
  <D:response>
    <D:href>/123456/calendars/home/</D:href>
  </D:response>
  <D:response>
    <D:href>/123456/calendars/work/</D:href>
    <D:propstat>
      <D:prop>
        <D:displayname>Work</D:displayname>
      </D:prop>
      <D:status>HTTP/1.1 200 OK</D:status>
    </D:propstat>
  </D:response>
</D:multistatus>"""

SAMPLE_EVENT_REPORT = """<?xml version="1.0" encoding="UTF-8"?>
<C:multistatus xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <D:response>
    <D:href>/123456/calendars/work/event.ics</D:href>
    <D:propstat>
      <D:prop>
        <C:calendar-data>BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:test-event-1
SUMMARY:Smith Residence
DESCRIPTION:Full exterior clean. Ticket $450
LOCATION:123 Oak St
DTSTART;VALUE=DATE:20240501
DTEND;VALUE=DATE:20240502
END:VEVENT
END:VCALENDAR
        </C:calendar-data>
      </D:prop>
      <D:status>HTTP/1.1 200 OK</D:status>
    </D:propstat>
  </D:response>
</C:multistatus>"""


def test_find_calendar_href_matches_display_name():
    import xml.etree.ElementTree as ET

    root = ET.fromstring(SAMPLE_CALENDAR_LIST)
    href = _find_calendar_href(root, "Work")
    assert href == "/123456/calendars/work/"


def test_parse_calendar_report_extracts_events():
    import xml.etree.ElementTree as ET

    root = ET.fromstring(SAMPLE_EVENT_REPORT)
    events = _parse_calendar_report(root, date(2024, 5, 1))
    assert len(events) == 1
    assert events[0].title == "Smith Residence"
    assert events[0].location == "123 Oak St"
    assert "450" in events[0].description
    assert events[0].event_id == "test-event-1"
