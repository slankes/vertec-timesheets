#!/usr/bin/python3
"""
Script extracting timesheets for the user.

source venv/bin/activate
pip3 install requests

export VERTEC_URL=
export VERTEC_USERNAME=
export VERTEC_PASSWORD=

python3 vertec-timesheets.py
"""

import os
import json
import logging
from getpass import getpass
from xml.sax.saxutils import escape as xmlescape
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from itertools import groupby

import requests

logging.basicConfig(level=logging.WARN)

# Vertec query to retrieve information about the currently logged-in user
QUERY_MY_USERS = """<Query>
    <Selection>
        <!-- Users whose team leader is the currently logged in user -->
        <ocl>projektbearbeiter->select(teamleiter.asstring=Timsession.allInstances->first.login.name)</ocl>
        <sqlorder>name</sqlorder>
    </Selection>
    <Resultdef>
        <member>name</member>
        <member>teamleiter</member>
        <member>eintrittper</member><!-- date of entry in the company -->
        <member>austrittper</member><!-- date when left the company -->
        <member>aktiv</member>
        <expression><alias>teamleiter_name</alias><ocl>teamleiter.name</ocl></expression>
        <expression><alias>stufe_name</alias><ocl>stufe</ocl></expression>
    </Resultdef>
</Query>"""

# Vertec query to retrieve information about the timesheets (leistungen) for the specified object (user, project, phase)
#    The object reference MUST be added as {param} parameter.
QUERY_TS = """<Query>
    <Selection>
        <!-- parameter is here the ID of a phase or user -->
        <objref>{param}</objref>
        <!-- All open and closed services for the selected project or phase-->
        <ocl>offeneleistungen->select((datum &gt;= date->firstOfMonth->incMonth(-1)) and (datum &lt; date->firstOfMonth))->orderby(datum)->union(verrechneteleistungen->select((datum &gt;= date->firstOfMonth->incMonth(-1)) and (datum &lt; date->firstOfMonth))->orderby(datum))</ocl>
        <sqlorder>datum</sqlorder>
    </Selection>
    <Resultdef>
        <!-- Details on fields: https://www.vertec.com/ch/kb/leistunginocl/ -->
        <member>datum</member>
        <member>minutenint</member>
        <member>wertint</member>
        <member>wertext</member>
        <member>text</member>
        <member>phase</member>
        <member>projekt</member>
        <member>bearbeiter</member>
        <expression><alias>bearbeiter_name</alias><ocl>bearbeiter.name</ocl></expression>
        <expression><alias>projekt_name</alias><ocl>projekt</ocl></expression>
        <expression><alias>phase_name</alias><ocl>phase.code</ocl></expression>
        <expression><alias>phase_is_billable</alias><ocl>phase.verrechenbar</ocl></expression>
    </Resultdef>
</Query>"""

def get_vertec_data(endpoint: str, token:str, query:str):
    """Queries the Vertec XML API and 'yields' the returned data to the caller as an iterator."""
    try:
        envelope = f"""<Envelope><Header><BasicAuth><Token>{token}</Token></BasicAuth></Header><Body>{query}</Body></Envelope>"""
        r = requests.request("POST", f"{endpoint}/xml", headers={'Content-Type': 'text/plain'}, data=envelope, timeout=30)
        r.raise_for_status()
        body_elem = ET.fromstring(r.text).find("Body")
        fault_elem = body_elem.find("Fault")
        if fault_elem:
            """
            <Fault>
                <faultcode>Client</faultcode>
                <faultstring>Error(s) in XML input</faultstring>
                <details>
                    <detailitem>Error: 84:Parenthesis are not in balance on line 10 col 22</detailitem>
                    <detailitem>Error: 0:This variable () has no value or type on line 19 col 43</detailitem>
                    <detailitem>Error: expression Element without ocl on line 20 col 25</detailitem>
                    <detailitem>Error: 0:This variable () has no value or type on line 23 col 44</detailitem>
                    <detailitem>Error: expression Element without ocl on line 24 col 25</detailitem>
                </details>
            </Fault>
            """
            d = {
                'fault_code': fault_elem.find("faultcode").text,
                'fault_string': fault_elem.find("faultstring").text,
                'details' : [],
                'query_executed': query
            }
            for det_item in fault_elem.find("details"):
                d['details'].append(det_item.text)

            yield d
            return

        for result in body_elem.find("QueryResponse"):
            """
            <Envelope>
            <Body>
                <QueryResponse>
                <ProjektPhase>
                    <objid>2699811</objid>
                    <aktiv>0</aktiv>
                    <planWertExt><accessdenied/></planWertExt>
                    <projekt>
                        <objref>2671828</objref>
                    </projekt>
            """
            #if len(list(e.iter("accessdenied"))) > 0:
            #    # user cannot access some fields of this data. what to do?!
            #    pass
            d = {}
            d['datatype'] = result.tag
            for field in result:
                field_elements = list(field.iter())
                if len(field_elements)==1:
                    # the iter() function returns the element itself as first result
                    # so if the list has length=1, the element does not have any children
                    d[field.tag] = field.text.strip() if field.text else None
                elif field_elements[-1].tag == "accessdenied":
                    d[field.tag] = "accessdenied"
                else:
                    d[field.tag] = field_elements[-1].text.strip() if field_elements[-1].text else None

            # the vertec API returns records also for objects which might not be accessible
            # and will set an "<accessdenied>" element as value of the return values.
            # I want to IGNORE such records and not yield them to the caller
            # In order to do this, I check for the field 'aktiv', which is generally related to projects and phases,
            # and ignore records where such field has an "accessdenied" value

            if d.get('aktiv', "whatever") != "accessdenied":
                yield d
    except requests.HTTPError as e:
        raise Exception(f"get_vertec_data: http error while retrieving vertec data. {e}")
    except Exception as e:
        raise Exception(f"get_vertec_data: exception when retrieving vertec data {type(e)} - {str(e)}")


def get_vertec_token(endpoint: str, username:str, password:str) -> str:
    """Connects to vertec and returns an authentication token to be used for subsequent API calls
    """
    try:
        r = requests.post(f"{endpoint}/auth/xml",
                headers={'Content-Type': 'application/x-www-form-urlencoded'},
                data=dict(vertec_username=username, password=password),
                timeout=5)
        r.raise_for_status()
        logging.debug(f"vertec: retrieved auth token from vertec")
        return r.text
    except requests.HTTPError as e:
        raise Exception(f"get_vertec_token: error while retrieving vertec auth token for username '{username}' {str(e)}")
    except Exception as e:
        raise Exception(f"get_vertec_token:: fatal error while retrieving vertec auth token: {str(e)}")


if __name__ == "__main__":
    try:
        url = os.environ.get("VERTEC_URL") or input(f"Vertec url (format: 'https://...'):")
        if url in ('', None):
            raise Exception("Provide the vertec URL as ENV variable VERTEC_URL or by interactive prompt")

        username = os.environ.get("VERTEC_USERNAME") or input(f"Vertec username:")
        if username in ('', None):
            raise Exception("Provide the vertec username as ENV variable VERTEC_USERNAME or by interactive prompt")

        password = os.environ.get("VERTEC_PASSWORD") or getpass(f"Vertec password for '{username}':")
        if password in ('', None):
            raise Exception("Provide the vertec password as ENV variable VERTEC_PASSWORD or by interactive prompt")

        # authenticate against vertec and cache the token
        logging.info(f"retrieving auth token from vertec server {url} for {username}")
        token = get_vertec_token(url, username, password)

        logging.info(f"getting ID of currently logged in user")
        for user in get_vertec_data(url, token, QUERY_MY_USERS):
            if (user['aktiv'] == '1'):
                print("\n\033[92m### %s (%s)\033[0m" % (user['name'], user['objid']))
                query = QUERY_TS.format(param=user['objid'])
                logging.info(f"executing query:\n{query}")

                # Get and sort rows by date.
                rows = list(get_vertec_data(url, token, query))
                rows.sort(key=lambda r: r['datum'])

                # Initialize expected_date to the first day of the month of the first booking.
                if rows:
                    first_date = datetime.strptime(rows[0]['datum'].strip(), "%Y-%m-%d")
                    expected_date = first_date.replace(day=1)
                else:
                    expected_date = None

                # Group rows by their date.
                for date_str, group in groupby(rows, key=lambda r: r['datum']):
                    current_date = datetime.strptime(date_str.strip(), "%Y-%m-%d")

                    # Print missing days from expected_date until we reach the current booking date.
                    # We compare full dates so that even if there are multiple bookings on one day,
                    # we only advance expected_date once.
                    while expected_date < current_date:
                        # Only print missing if it's a weekday (0=Monday, ..., 4=Friday)
                        if expected_date.weekday() < 5:
                            print(f"{expected_date.strftime('%Y-%m-%d')} - MISSING")
                        expected_date += timedelta(days=1)

                    # Optionally print a blank line if current_date is a Monday.
                    if current_date.weekday() == 0:
                        print()

                    # Process all rows for the current_date.
                    for row in group:
                        print(f"{row['datum']} - {row['projekt_name']:<30} | {row['phase_name']:<40} :: {round(float(row['minutenInt']) / 60, 1)}")

                    # Advance expected_date by one day after processing the current date.
                    expected_date += timedelta(days=1)

    except Exception as e:
        logging.fatal(str(e))
