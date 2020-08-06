# recreation.gov scraper. Finds specified campsites and send you a link to book.
# possible todos: 
# actually book automatically.
# build a frontend for display
# collect data on cancellations and analyze the best time to book 

import requests
from bs4 import BeautifulSoup
import sys
import datetime
from datetime import timedelta
import json
import smtplib
from dateutil.relativedelta import relativedelta
import _keys

#wildcat will need to specify loop
##GLOBALS## 
campground_ids = {
	#recreation.gov id: [campground name, loop name]
    232069: ["lone pine", None],
    232491: ["kirby cove", None],
    232447: ["upper pines", None],
}
start_date = datetime.datetime.today().replace(day=1) + relativedelta(months=1)
end_date = datetime.datetime.today() + relativedelta(months=12)
#day of the week to check in and out
check_in = 4
check_out = 6

#number of weeks to stay
num_weeks = 1

#request camp availability data from the api and convert to json.
def get_campground_data(search_date, campground_id):
    url = """https://www.recreation.gov/api/camps/availability/campground/{0}/month?start_date={1}T00:00:00.000Z""".format(campground_id, search_date.strftime("%Y-%m-%d"))
    print(url)
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/77.0.3865.90 Safari/537.36"}
    req = requests.get(url, headers=headers)
    campground_data = json.loads(req.text)
    return campground_data

#returns {campsite_key: [dates]}
def parse_available_dates(campground_data, loop=None):
    available_dates = {}
    campsite_keys = campground_data['campsites'].keys()
    for campsite_key in campsite_keys:
        #if campsite_key != '67031': continue
        #if we specified a loop, only pull campsites in the loop
        if loop != None and campground_data['campsites'][campsite_key][loop] != loop:
            continue
        for date, status in campground_data['campsites'][campsite_key]['availabilities'].items():
            if status == 'Available':
                if campsite_key not in available_dates.keys(): available_dates[campsite_key] = []
                available_dates[campsite_key].append(datetime.datetime.strptime(date, '%Y-%m-%dT%H:%M:%SZ'))
    return available_dates

#here, new will be one month of one campground processed by 'parse_available_dates'. 
#We want to add this to the master list
#if the campground already exists in the master list, we merge the lists of dates by campsite
#if the campground is new to the master list, we add the campground to the list
def merge_dicts(existing, new, campground_id):
    if campground_id in existing.keys():
        for campsite_id in new.keys():
            if campsite_id in existing[campground_id].keys():
                existing[campground_id][campsite_id].extend(new[campsite_id])
            else:
                existing[campground_id][campsite_id] = new[campsite_id]
    else:
        existing[campground_id] = new

    return existing

def get_campground_metadata(campground_data):
    #What's the output i want to see?
    # -campground name
    # -campground id
    # -campsite (site is different from campsite id)
    # -loop
    # -max capacity
    campground_metadata = {}
    for campsite_id, data in campground_data['campsites'].items():
        campground_metadata[campsite_id] = [data['loop'], data['max_num_people'], data['site']]

    return campground_metadata


def collect_and_parse_campground_data(campground_ids, start_date, end_date):
    campground_dates = {}
    campground_metadata = {}
    #iterate through each park
    #TODO: set start and end dates dynamically
    #another approach- we can get the raw data from a request by month
    #https://www.recreation.gov/api/camps/availability/campground/232069/month?start_date=2020-05-01T00%3A00%3A00.000Z
    # Not Reservable : first come first serve
    # Open : not yet released?
    # Available: Available
    # Reserved : Reserved 
    # if a date isn't in there, that means the campsite isn't open
    #you can login with a POST of request payload {username: "", password: ""} to https://www.recreation.gov/api/accounts/login
    search_date = start_date
    for campground_id, data in campground_ids.items():
        campground_name = data[0]
        loop = data[1]
        while search_date < end_date:
            print(search_date)
            campground_data = get_campground_data(search_date, campground_id)
            available_dates = parse_available_dates(campground_data, loop)
            #now we have a month of available dates for this campground, by campsite. we want to update the master dict with this info.
            campground_dates = merge_dicts(campground_dates.copy(), available_dates.copy(), campground_id)
            campground_metadata[campground_id] = get_campground_metadata(campground_data)
            search_date = search_date + relativedelta(months=1)
    return campground_dates, campground_metadata


#{campground_id:{campsite_id: [dates]}}

def get_specific_days(campground_dates, check_in=4, check_out=6, num_weeks=1):
    #this is a kind of complicated problem that I should logic out. 
    #i'm basically looking for subranges of consecutive dates within the dates 'bag'
    #loop just once; setting a temp for the previous 'good date' found
    #then if the next date is just one day ahead, and less than the checkout weekday, it's added to the dict, and
    # becomes the new 'good' date.
    # if it's equal to the checkout date; start a new series??
    # another wrinkle is checkouts less than checkin; eg, sunday - tuesday. 
    # one way to add 7 to the checkout and use mod

    specified_range_availabilities = {}

    for campground_id, campsite_dict in campground_dates.items():
        specified_range_availabilities[campground_id] = {}

        for campsite_id, campsite_dates in campsite_dict.items():
            specified_range_availabilities[campground_id][campsite_id] = []
            weekday = check_in
            dummy = datetime.datetime(2100,1,1)
            tmp_range = []
            campsite_dates.sort()

            for campsite_date in campsite_dates:
                if campsite_date.weekday() == weekday % 7:
                    #if this weekday is the start of a new range, or a consecutive date from an existing range
                    if (len(tmp_range) == 0) or (campsite_date == dummy + timedelta(days=1)):
                        tmp_range.append(campsite_date)
                        dummy = campsite_date
                        weekday += 1
                        #print(tmp_range)
                        if weekday % (7*num_weeks) == check_out:
                            print("weekday:", weekday)
                            specified_range_availabilities[campground_id][campsite_id].append(tmp_range[0])
                            dummy = datetime.datetime(2100,1,1)
                            tmp_range = []
                            weekday = check_in
                #if the campsite has incomplete availability, we don't want to include those dates
                #we'd know if this if the dates aren't consecutive.
                #then we will have to reset to the next group. 
                elif (len(tmp_range) > 0):
                    dummy = datetime.datetime(2100,1,1)
                    tmp_range = []
                    weekday = check_in


    return specified_range_availabilities


def generate_link_text(dates, campground_ids, campground_metadata):
    message = ""
    for campground_id, campsite_availability_dict in dates.items():
        if len(campsite_availability_dict) > 0:
            message += "Congratulations, " + campground_ids[campground_id][0] + " is available for your days \n" 
            for campsite_id, datelist in campsite_availability_dict.items():
                message += "at campsite " + \
                campground_metadata[campground_id][campsite_id][2] + " ({0})".format(campground_metadata[campground_id][campsite_id][1]) + \
                " starting on: "
                for date in datelist:
                    message += datetime.datetime.strftime(date, "%Y-%m-%d") + ", "
                message = message[:-2]
                message += ". book at https://www.recreation.gov/camping/campsites/{0}".format(campsite_id)
                message += '\n'
    return message




campground_dates, campground_metadata = collect_and_parse_campground_data(campground_ids, start_date, end_date)
weekends = get_specific_days(campground_dates, check_in=4, check_out=6, num_weeks=1)
message = generate_link_text(weekends, campground_ids, campground_metadata)

print(weekends)
print(campground_metadata)
print(message)

webhook = _keys._webhook_key 
headers = {"Content-type": "application/json"}
req = requests.post(url=webhook, headers=headers, data="{'text':'%s'}" % message)
print(req.text)
