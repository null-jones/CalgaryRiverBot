import pandas as pd
import numpy as np
import tweepy
import os
from io import BytesIO

from matplotlib import pyplot as plt
import seaborn as sns

# Imports twitter keys so they're not on github :)
from keys import *

RIVER_DATA_API_URL = "https://data.calgary.ca/resource/5fdg-ifgr.json"

MARKERS = {"Safe": "🟢", "Warn": "🟡", "Danger": "🔴"}

#Dictionary - Key corresponds to Station code.
MARKER_LEVELS = {
    "05BJ001": {
        "flow": {20: MARKERS["Safe"], 35: MARKERS["Warn"], 50: MARKERS["Danger"],},
    },
}

#Stations we'll use (There's more than this), Key is station code, Val is verbose name
STATIONS = {
    "05BH004": "Bow River at Calgary",
    "05BJ001": "Elbow River below Glenmore Dam",
    "05BJ008": "Glenmore Reservoir at Calgary",
    "05BH005": "Bow River near Cochrane",
    "05BJ004": "Elbow River at Bragg Creek",
}

STATION_NAME_MAP = {
    "Bow River at Calgary": "Bow - YYC",
    "Elbow River below Glenmore Dam": "Elbow blw. Glenmore",
    "Glenmore Reservoir at Calgary": "Glenmore Resevoir",
    "Bow River near Cochrane": "Bow - Cochrane",
    "Elbow River at Bragg Creek": "Elbow - Bragg Creek",
}

#Used for aggregating the data (if you need to!)
AGGREGATE_COLUMNS = {
    "level": np.mean,
    "level_min": np.min,
    "level_max": np.max,
    "flow": np.mean,
    "flow": np.min,
    "flow": np.max,
}


def main():
    # Pulls main file (only way to get the most recent data for some reason)
    # Defaults to 6:15AM of the day you request if you try and aggregate
    df = pull_all_recent_stations()

    # Pulls the 4 main river stations
    glenmore = pull_station("05BJ008", pull_from_df=df)
    bow = pull_station("05BH004", pull_from_df=df)
    elbow = pull_station("05BJ001", pull_from_df=df)
    bow_c = pull_station("05BH005", pull_from_df=df)

    # Generates string for tweeting
    tweet_str = gen_tweet_str(
        bow.iloc[0], elbow.iloc[0], glenmore.iloc[0], bow_c.iloc[0]
    )

    # Generates the charts and slams them into some good ol file buffers
    buf1, buf2 = gen_charts([bow_c, bow, elbow], [bow_c, bow, elbow])

    # Tweets the details!
    tweet_general_update(
        tweet_str, [(buf1, "flow.png"), (buf2, "level.png")],
    )

    return True


def pull_station(station_number, aggregate=False, limit=5000, pull_from_df=False):
    # Checks the station name is correct
    if station_number not in STATIONS.keys():
        return False

    # Pull River data
    if pull_from_df is False:
        df = pd.read_json(
            f"{RIVER_DATA_API_URL}?station_number={station_number}&$order=timestamp%20DESC&$limit={round(limit, 0)}"
        ).set_index("timestamp")
    else:
        df = pull_from_df[pull_from_df["station_number"] == station_number]

    # Convert level and flow columns to numeric, and coerce errors to NaN instead of "NA" string
    df[["level", "flow"]] = df[["level", "flow"]].apply(
        pd.to_numeric, errors="coerce", axis=1
    )

    if aggregate:
        # Create placeholder columns for min/max calculations
        df["level_min"], df["level_max"] = df["level"], df["level"]
        df["flow_min"], df["flow_max"] = df["flow"], df["flow"]
        # Resample and aggregate w/ avg, min and max - unused currently
        df = df.resample("1D").agg(AGGREGATE_COLUMNS).fillna(0)

    return df


def pull_all_recent_stations(aggregate=False, limit=20000):
    #Returns a dataframe w/ recent data
    return pd.read_json(f"{RIVER_DATA_API_URL}?$limit={round(limit, 0)}").set_index(
        "timestamp"
    )


def gen_tweet_str(bow, elbow, glenmore, bow_c):
    # Takes one row for each detail.  Replaces NaN w/ N/A for clarity.  Yum f-strings are my jam
    return f"""River Stats {bow.name.strftime("%m/%d/%Y %H:%M %p")}
Bow Cochrane: {round(bow_c["flow"], 2) if not np.isnan(bow_c["flow"]) else "N/A"} m3/min, {round(bow_c["level"], 2)} m
Bow YYC: {round(bow["flow"], 2) if not np.isnan(bow["flow"]) else "N/A"} m3/min, {round(bow["level"], 2)} m
Elbow YYC: {status_symbol(elbow["station_number"], elbow["flow"])}: {round(elbow["flow"], 2) if not np.isnan(elbow["flow"]) else "N/A"} m3/min, {round(elbow["level"], 2)} m
Glenmore Resevoir: {round(glenmore["level"], 0)} m
"""


def status_symbol(station_number, flow):
    if station_number in MARKER_LEVELS.keys():
        for key, value in MARKER_LEVELS[station_number]["flow"].items():
            if flow < key:
                return value
        return MARKERS["Danger"]
    else:
        return ""


def gen_charts(df_flow_list, df_level_list):
    # Concats df lists into single dataframes
    flow_dfs = pd.concat(df_flow_list)
    level_dfs = pd.concat(df_level_list)

    # Renames columns, stations, and resets indecies (Needed to plot)
    for df in [flow_dfs, level_dfs]:
        df.reset_index(inplace=True)
        df.rename(
            inplace=True,
            columns={
                "timestamp": "Date",
                "flow": "Flow (m3/s)",
                "level": "Level (m)",
                "station_name": "Location",
            },
        )
        df.replace({"Location": STATION_NAME_MAP}, inplace=True)

    # Gotta make it look pretty!
    sns.set(style="darkgrid")

    return (
        plot_chart(df, "Date", "Flow (m3/s)", "Location", None, return_buffer=True),
        plot_chart(df, "Date", "Level (m)", "Location", None, return_buffer=True),
    )

    return True


def plot_chart(df, x_str, y_str, hue_str, file_name, return_buffer=False):
    # Stock seaborn lineplot func
    ax = sns.lineplot(x=x_str, y=y_str, hue=hue_str, data=df)

    # Annotate axes w/ twitter handle, etc.
    ax.text(
        0.95,
        0.01,
        "By @CalgaryRiverBot on Twitter",
        verticalalignment="bottom",
        horizontalalignment="right",
        transform=ax.transAxes,
        fontsize=8,
    )

    # Remove x-axis title, it's pretty obvious, no need for that to take up space lol
    ax.set(xlabel=None)

    # Rotating x-ticks to display correctly
    plt.xticks(rotation=30)
    plt.tight_layout()

    # If we don't want a file buffer save it as an image w/ file_name
    if not return_buffer:
        plt.savefig(file_name)
        plt.close()
        return True
    else:
        buf = BytesIO()
        plt.savefig(buf, format="png")
        plt.close()
        buf.seek(0)
        return buf


def tweet_general_update(tweet_str, image_list):
    # Auth twitter account
    # pull env variables used in prod.
    # pull_environment_variables()
    api = tweepy_auth()

    # Uploads images
    media_list = []
    for image, image_name in image_list:
        response = api.media_upload(image_name, file=image)
        media_list.append(response.media_id_string)

    # Send Tweet
    api.update_status(status=tweet_str, media_ids=media_list)


def tweepy_auth():
    # authentication of consumer key and secret
    auth = tweepy.OAuthHandler(CONSUMER_KEY, CONSUMER_SECRET)
    # authentication of access token and secret
    auth.set_access_token(ACCESS_TOKEN, ACCESS_TOKEN_SECRET)
    return tweepy.API(auth)


def pull_environment_variables():
    # Pulls environment variables for AWS Lambda.  Modify this if you're running it on your own machine
    CONSUMER_KEY = os.getenv("CRB_CONSUMER_KEY")
    CONSUMER_SECRET = os.environ["CRB_CONSUMER_SECRET"]
    ACCESS_TOKEN = os.environ["CRB_ACCESS_TOKEN"]
    ACCESS_TOKEN_SECRET = os.environ["CRB_ACCESS_TOKEN_SECRET"]

    return True


if __name__ == "__main__":
    main()
