import time
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
from sqlalchemy import (
    INTEGER,
    JSON,
    TIMESTAMP,
    Column,
    Integer,
    MetaData,
    Table,
    Text,
    create_engine,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, insert
from sqlalchemy.sql import func
from sqlalchemy.types import BIGINT, JSON, TEXT, TIMESTAMP, Integer

# from lineups import fetch_all_lineups
# from fixture_events import fetch_all_events

conn_string = "postgres_connection_string"
engine = create_engine(conn_string)

def update_fixtures(leagues):
    def fetch_fixtures(data):
        """
        Fetches all pages for the given API endpoint and saves each page and the combined data.
        """
        # Set your API key here
        API_KEY = 'api_key'  # <-- Replace with your real API key

        headers = {
            'x-rapidapi-host': "v3.football.api-sports.io",
            'x-rapidapi-key': API_KEY
            }


        base_url = 'https://v3.football.api-sports.io/fixtures'
        params = {'league': data["league"], "season": data['season']}
        resp = requests.get(base_url, headers=headers, params=params)
        if resp.status_code != 200:
            print(f"Error fetching data from {base_url}: {resp.status_code}")

        res = resp.json()
        if "response" in res and len(res["response"]) != 0:
            time.sleep(65/300)
            return res["response"]
        
    def parse_fixtures(row):
        data = {}
        data["id"] = row["fixture"]["id"]
        data["status"] = row["fixture"]["status"]["short"]
        data["referee"] = row["fixture"]["referee"]
        # data["venue"] = row["fixture"]["venue"]
        data["start"] = row["fixture"]["timestamp"]
        # data["commence_time"] = row["fixture"]["date"]
        data["home_team"] = row["teams"]["home"]["name"]
        data["home_id"] = str(row["teams"]["home"]["id"])
        data["away_team"] = row["teams"]["away"]["name"]
        data["away_id"] = str(row["teams"]["away"]["id"])
        data["tournament"] = row["league"]["name"]+";"+row["league"]["country"]
        data["tid"] = str(row["league"]["id"])
        data["season"] = row["league"]["season"]
        data["score"] = row["score"]
        # data["statistics"] = goalsToStats(row["score"])
        return data

    def upsert_on_conflict(table, conn, keys, data_iter):
        data = [dict(zip(keys, row, strict=False)) for row in data_iter]
        
        if not data:
            return
        
        insert_stmt = insert(table.table).values(data)
        
        # Update all columns except id and created_at on conflict
        update_dict = {
            col.name: insert_stmt.excluded[col.name]
            for col in table.table.columns
            if col.name not in ['id', 'created_at']
        }
        
        upsert_stmt = insert_stmt.on_conflict_do_update(
            index_elements=['id'],
            set_=update_dict
        )
        
        conn.execute(upsert_stmt)
        
    # ldf = pd.DataFrame(leagues).explode("year")
    ldf = leagues.copy()
    ldf = (
        ldf[
        ldf.current
        ]
        .reset_index(drop=True)
        .sort_values(["year", "league.id"], ascending = [False, True])
        .rename(columns = {"year": "season", "league.id": "league"})
        .reset_index(drop=True).to_dict("records"))
    for i, data in enumerate(ldf):
        print(f"{i+1}/{len(ldf)}:- League ID: {data['league']}, season: {data['season']}")
        fixtures_data = fetch_fixtures(data)
        if fixtures_data is None:
            print(f"No fixtures data for League ID: {data['league']}, season: {data['season']}")
            continue

        fixtures_parsed = [parse_fixtures(row) for row in fixtures_data]
        fixtures_df = pd.DataFrame(fixtures_parsed)

        # Filter to only include fixtures in updateFixtures
        # fixtures_df = fixtures_df[fixtures_df["id"].isin(fixtures_list)].reset_index(drop=True)

        if fixtures_df.empty:
            print(f"No matching fixtures to update for League ID: {data['league']}, season: {data['season']}")
            continue

        # Convert start time to datetime with Berlin timezone
        fixtures_df["start"] = pd.to_datetime(fixtures_df["start"], unit='s', utc = True).dt.tz_convert(ZoneInfo('Europe/Berlin'))
        current_time = datetime.now(ZoneInfo('Europe/Berlin'))
        fixtures_df['created_at'] = current_time
        fixtures_df['updated_at'] = current_time
        fixtures_dtype = {
            "id": BIGINT,
            'start': TIMESTAMP(timezone=True),
            'home_team': TEXT,
            'home_id': TEXT,
            'away_team': TEXT,
            'away_id': TEXT,
            'tournament': TEXT,
            'tid': TEXT,
            'status': TEXT,
            'referee': TEXT,
            'season': Integer,
            "score": JSON,
            'created_at': TIMESTAMP(timezone=True),
            'updated_at': TIMESTAMP(timezone=True),
            }
        
        # Upsert into the database
        
        fixtures_df.to_sql(
            'apifootball', engine, if_exists='append', index=False, dtype=fixtures_dtype, method = upsert_on_conflict, chunksize=1000
        )
    print('Fixtures Done')
    return fixtures_df

def update_statistics(updateFixtures, leagues):
    
    def fetch_statistics(fixture_id, half=True):
        """
        Fetch statistics for a single fixture.
        If half=True, try half-time stats first; if empty, fall back to full-match stats.
        Returns:
            dict | None:
            - dict with 'scope' and 'data' keys if stats exist
            - None if no stats at all
        """
        base_url = 'https://v3.football.api-sports.io/fixtures/statistics'
        headers = {
            'x-rapidapi-host': "v3.football.api-sports.io",
            'x-rapidapi-key': "api_key"
        }

        def _call_api(params):
            try:
                resp = requests.get(base_url, headers=headers, params=params)
                if resp.status_code != 200:
                    print(f"Error fetching fixture {fixture_id}: {resp.status_code}")
                    return None
                time.sleep(65/300)  # rate limit
                data = resp.json()
                return data.get("response", [])
            
            except Exception as e:
                print(f"Exception for fixture {fixture_id}: {e}")
                return None

        # 1) If half=True, try half-time stats first
        if half:
            params_half = {'fixture': fixture_id, 'half': 'true'}
            resp_half = _call_api(params_half)

            if resp_half is None:
                return None  # error or parsing issue

            if len(resp_half) > 0:
                # Case 1: half stats exist
                return {
                    "scope": "half",
                    "data": resp_half
                }

            # len(resp_half) == 0  -> no half stats, fall back to full match

        # 2) Try full-match stats (either half=False or half=True but empty)
        params_full = {'fixture': fixture_id}
        resp_full = _call_api(params_full)

        if resp_full is None or len(resp_full) == 0:
            # Case 3: no stats at all

            # print(f"No statistics (half or full) available for fixture {fixture_id}")
            return {}

        # Case 2: only full-match stats exist
        return {
            "scope": "full",
            "data": resp_full
        }

    def process_statistics(res):
        data = res.get("data", [])
        if len(data) == 0:
            return None
        scope = res.get("scope", "full")
        df = pd.DataFrame(data)
        df["team_id"] = df["team"].apply(lambda x: x["id"])
        df["fixture_id"] = id
        # df["scope"] = scope
        return df.drop(columns =["team"])
        
    ldf = pd.DataFrame(leagues).explode("year")
    ldf = ldf[
        ldf.coverage.apply(lambda x: x["fixtures"]["statistics_fixtures"])
        ].reset_index(drop=True).sort_values(["year", "league.id"], ascending = [False, True]).reset_index(drop=True)
    
    ldf["league_season"] = ldf["league.id"].astype(str) + ";" + ldf["year"].astype(str)
    updateFixtures["league_season"] = updateFixtures["tid"].astype(str) + ";" + updateFixtures["season"].astype(str)
    updateFixtures = updateFixtures[updateFixtures["league_season"].isin(ldf.league_season)].reset_index(drop=True)       
    fixtures_list = updateFixtures.id.unique().tolist()   
    for i, id in enumerate(fixtures_list):
        print(f"{i+1}/{len(fixtures_list)}:- Fixture ID: {id}")
        stats = fetch_statistics(id, half=True)
        if stats is None:
            print(f"Error fetching statistics for fixture ID: {id}")
            continue
        df_stats = process_statistics(stats)
        if df_stats is None:
            print("    No statistics available")
            continue
        
        dtype_stats = {
            "fixture_id": BIGINT,
            "team_id": INTEGER,
            "statistics": JSON,
            'statistics_1h': JSON,
            'statistics_2h': JSON,
            'created_at': TIMESTAMP(timezone=True),
            'updated_at': TIMESTAMP(timezone=True),
        }
        
        def upsert_on_conflict_stats(table, conn, keys, data_iter):
            data = [dict(zip(keys, row, strict=False)) for row in data_iter]
            
            if not data:
                return
            
            insert_stmt = insert(table.table).values(data)
            
            # Update all columns except id and created_at on conflict
            update_dict = {
                col.name: insert_stmt.excluded[col.name]
                for col in table.table.columns
                if col.name not in ['team_id','fixture_id', 'created_at']
            }
            
            upsert_stmt = insert_stmt.on_conflict_do_update(
                constraint="fixture_stats_team_fixture_uniq",
                set_=update_dict,
            )
            conn.execute(upsert_stmt)
        current_time = datetime.now(ZoneInfo('Europe/Berlin'))
        df_stats['created_at'] = current_time
        df_stats['updated_at'] = current_time
        
        df_stats.to_sql(
            'fixture_stats', engine, if_exists='append', index=False, dtype=dtype_stats, method = upsert_on_conflict_stats, chunksize=1000
        )
        print("     Upserting statistics data into database...")        

def update_player_statistics(updateFixtures, leagues):
    def fetch_players_statistics(fixture_id):
        """
        Fetch predictions for a single fixture and save with fixture ID as key.

        Args:
            fixture_ids (list): List of fixture IDs to fetch predictions for

        Returns:
            dict: Dictionary with fixture IDs as keys and prediction data as values
        """

        def parse_player_statistics(data):
            df = pd.DataFrame(data)
            df["fixture_id"] = fixture_id
            df['team_id'] = df.team.apply(lambda x: x['id'])
            df = df.explode('players')
            df['player_id'] = df.players.apply(lambda x: x['player']['id'])

            # df['name'] = df.players.apply(lambda x: x['player']['name'])
            df['statistics'] = df.players.apply(lambda x: x['statistics'])
            df = df.drop(columns=['players', "team"]).explode('statistics').reset_index(drop=True)
            df = df.drop(columns = "statistics").merge(df.statistics.apply(pd.Series), left_index=True, right_index=True)
            df.offsides = df.offsides.fillna(0).apply(int)
            def add_offside(d, v):
                d = dict(d)              # copy, in case you don't want to modify in place
                d["offsides"] = v
                return d

            df.goals = df.apply(lambda x: add_offside(x.goals, x.offsides), axis=1)
            df = df.drop(columns = "offsides")
            df = df[df.player_id != 0]
            return df


        base_url = 'https://v3.football.api-sports.io/fixtures/players'

        headers = {
        'x-rapidapi-host': "v3.football.api-sports.io",
        'x-rapidapi-key': "api_key"
        }


        params = {
            'fixture': fixture_id
            }

        try:
            response = requests.get(base_url, headers=headers, params=params)
            if response.status_code == 200:
                time.sleep(65/300)
                data = response.json()

                if len(data["response"]) == 0:
                    print("    No player statistics available")
                    return pd.DataFrame()
                else:
                    return parse_player_statistics(data['response'])
            else:
                print(f"Error fetching fixture {fixture_id}: {response.status_code}")
                return pd.DataFrame()

        except Exception as e:
            print(f"Exception for fixture {fixture_id}: {e!s}")
            return pd.DataFrame()


    def save_to_postgres(df, table_name="player_stats"):
            current_time = datetime.now(ZoneInfo('Europe/Berlin'))
            
            # Add timestamp columns to DataFrame
            df['created_at'] = current_time
            df['updated_at'] = current_time
            
            # Custom upsert method
            def upsert_on_conflict_players(table, conn, keys, data_iter):
                data = [dict(zip(keys, row, strict=False)) for row in data_iter]
                
                if not data:
                    return
                
                insert_stmt = insert(table.table).values(data)
                
                # Update all columns except e_id (primary key) and created_at
                update_dict = {
                    col.name: insert_stmt.excluded[col.name]
                    for col in table.table.columns
                    if col.name not in ['player_id',"fixture_id","team_id",'created_at']
                }
                
                upsert_stmt = insert_stmt.on_conflict_do_update(
                    index_elements=['player_id', "team_id", 'fixture_id'],  # Primary key
                    set_=update_dict
                )
                
                conn.execute(upsert_stmt)
            
            df.to_sql(
                table_name, 
                engine, 
                if_exists="append", 
                index=False,
                dtype={
                    "player_id": BIGINT,
                    'team_id': BIGINT,
                    "fixture_id": BIGINT,
                    'created_at': TIMESTAMP(timezone=True),
                    'updated_at': TIMESTAMP(timezone=True),
                    "games": JSON,
                    "shots": JSON,
                    "goals": JSON,
                    "passes": JSON,
                    "tackles": JSON,
                    "duels": JSON,
                    "dribbles": JSON,
                    "fouls": JSON,
                    "cards": JSON,
                    "penalty": JSON,
                },
                method=upsert_on_conflict_players  # Add custom method here
            )

        
    
    ldf = pd.DataFrame(leagues).explode("year")
    ldf = ldf[
        ldf.coverage.apply(lambda x: x["fixtures"]["statistics_players"])
        ].reset_index(drop=True).sort_values(["year", "league.id"], ascending = [False, True]).reset_index(drop=True)
    
    ldf["league_season"] = ldf["league.id"].astype(str) + ";" + ldf["year"].astype(str)
    updateFixtures["league_season"] = updateFixtures["tid"].astype(str) + ";" + updateFixtures["season"].astype(str)
    updateFixtures = updateFixtures[updateFixtures["league_season"].isin(ldf.league_season)].reset_index(drop=True)       
    fixtures_list = updateFixtures.id.unique().tolist()
    q = """
    SELECT id FROM apifootball af LEFT JOIN player_stats fs ON af.id = fs.fixture_id
    WHERE fs.fixture_id is NULL
    AND af.start >= NOW() -INTERVAL '7 days' AND af.start <= NOW()
    """
    # ids = pd.read_sql(q, engine)
    # fixtures_list = [x for x in fixtures_list if x in ids.id]
    for i, fixture_id in enumerate(fixtures_list):
        
        print(f"{i+1}/{len(fixtures_list)}:- Fixture ID: {fixture_id}")
        df_players = fetch_players_statistics(fixture_id)
        if df_players.empty:
            print(f"No player statistics for fixture ID: {fixture_id}")
            continue
        save_to_postgres(df_players, table_name="player_stats")
        print("     Upserting player statistics data into database...")

def fetch_all_leagues():
    """
    Fetches all leagues with available metrics available on api sports.
    """
    # Set your API key here
    API_KEY = 'api_key'  # <-- Replace with your real API key

    headers = {
        'x-rapidapi-host': "v3.football.api-sports.io",
        'x-rapidapi-key': API_KEY
        }


    base_url = 'https://v3.football.api-sports.io/leagues'

    params = {}
    resp = requests.get(base_url, headers=headers, params=params)

    if resp.status_code != 200:
        print(f"Error fetching leagues: {resp.status_code}")

    else:
        data = resp.json()
        if "response" in data and len(data["response"]) != 0:
            print(f"Fetched {len(data['response'])} leagues")

    leagues_df = pd.json_normalize(data['response']).explode("seasons").reset_index(drop=True)
    
    # Convert to DataFrame for easier handling
    leagues_df = (
        leagues_df
        .drop(columns = "seasons")
        .merge(leagues_df.seasons.apply(pd.Series), left_index = True, right_index = True)
        )

    return leagues_df

def fetch_all_events(updateFixtures, leagues):
    def fetch_events(fixture_id):
        """
        Fetch events for a single fixture and save with fixture ID as key.

        Args:
            fixture_ids (list): List of fixture IDs to fetch predictions for

        Returns:
            dict: Dictionary with fixture IDs as keys and prediction data as values
        """
        
        def parse_events(data):
            df = pd.DataFrame(data)      
            df["team"] = df["team"].apply(lambda x: x["id"])
            df['player'] = df['player'].apply(lambda x: x.get('id') if isinstance(x, dict) else None).astype('Int64')
            df['assist'] = df['assist'].apply(lambda x: x.get('id') if isinstance(x, dict) else None).astype('Int64')
            payload = df.to_dict(orient='records')
            return payload

        base_url = 'https://v3.football.api-sports.io/fixtures/events'

        headers = {
        'x-rapidapi-host': "v3.football.api-sports.io",
        'x-rapidapi-key': "api_key"
        }

        params = {
            'fixture': fixture_id
            }

        try:
            response = requests.get(base_url, headers=headers, params=params)
            if response.status_code == 200:
                time.sleep(65/300)
                data = response.json()
                if len(data["response"]) == 0:
                    print(f"No events available for fixture {fixture_id}\n")
                    return pd.DataFrame()
                else:
                    datein = {}
                    datein["fixture"] = fixture_id
                    datein["events"] = parse_events(data['response'])
                    
                    return pd.Series(datein)
            else:
                print(f"Error fetching events fixture {fixture_id}: {response.status_code}")
                return pd.DataFrame()

        except Exception as e:
            print(f"Exception for events of fixture {fixture_id}: {e!s}")
            return pd.DataFrame()
    
    def save_events_to_db(df_events):
        """Save events DataFrame to the database"""
        if df_events.empty:
            print("No events to save.")
            return
        
        current_time = datetime.now(tz=ZoneInfo("Europe/Berlin"))
        df_events['created_at'] = current_time
        df_events["updated_at"] = current_time          
        
        dtype_mapping = {
            "fixture": BIGINT,
            "events": JSON,
            # "team": INTEGER,
            # "player": INTEGER,
            # "assist": INTEGER,
            # "time": JSON,
            # "type": TEXT,
            # "detail": TEXT,
            # "comments": TEXT,
            "created_at": TIMESTAMP(timezone=True),
            "updated_at": TIMESTAMP(timezone=True)
        }
        
        with engine.connect() as conn:
            df_events.to_sql(
                'fixture_events',
                conn,
                if_exists='append',
                index=False,
                dtype=dtype_mapping
            )
        print(f"Saved {len(df_events)} event records to the database.")
    
    
    ldf = pd.DataFrame(leagues).explode("year")
    ldf = ldf[
        ldf.coverage.apply(lambda x: x["fixtures"]["events"])
        ].reset_index(drop=True).sort_values(["year", "league.id"], ascending = [False, True]).reset_index(drop=True)
    
    ldf["league_season"] = ldf["league.id"].astype(str) + ";" + ldf["year"].astype(str)
    updateFixtures["league_season"] = updateFixtures["tid"].astype(str) + ";" + updateFixtures["season"].astype(str)
    updateFixtures = updateFixtures[updateFixtures["league_season"].isin(ldf.league_season)].reset_index(drop=True)       
    fixtures_list = updateFixtures.id.unique().tolist()   
    q = """
    SELECT id FROM apifootball af LEFT JOIN player_stats fs ON af.id = fs.fixture_id
    WHERE fs.fixture_id is NULL
    AND af.start >= NOW() -INTERVAL '7 days' AND af.start <= NOW()
    """
    ids = pd.read_sql(q, engine)
    fixtures_list = [x for x in fixtures_list if x in ids.id]
    for i, fixture_id in enumerate(fixtures_list):
        print(f"{i+1}/{len(fixtures_list)}:- Fixture ID: {fixture_id}")
        df_ = fetch_events(fixture_id)

        if df_.empty:
            continue
        save_events_to_db(df_.to_frame().T)
            # events = pd.DataFrame()  # Reset after saving
    
    # return events

def fetch_all_lineups(updateFixtures, leagues):
    def fetch_lineups(fixture_id):
        """
        Fetch lineups for a single fixture and save with fixture ID as key.

        Args:
            fixture_ids (list): List of fixture IDs to fetch predictions for

        Returns:
            dict: Dictionary with fixture IDs as keys and prediction data as values
        """
        def convert_to_serializable(obj):
            """Recursively convert numpy types to native Python types."""
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            elif isinstance(obj, np.integer):
                return int(obj)
            elif isinstance(obj, np.floating):
                return float(obj)
            elif isinstance(obj, list):
                return [convert_to_serializable(i) for i in obj]
            elif isinstance(obj, dict):
                return {k: convert_to_serializable(v) for k, v in obj.items()}
            return obj
            
        def parse_lineups(row):
        
            # Extract team id as plain int
            row["team"] = row["team"].get("id", None)

            # Clean coach dict: remove photo, cast id to int, sanitize numpy types
            row["coach"] = convert_to_serializable({
                k: (int(v) if k == "id" and v is not None else v)
                    for k, v in row["coach"].items() if k != "photo"
                })

            if "startXI" in row.keys():
                row["startxi"] = convert_to_serializable([
                    {
                        k: (int(v) if k == "id" and v is not None else v)
                            for k, v in x["player"].items()
                            if k in ["id", "pos", "grid"]
                        }
                        for x in row["startXI"]     
                    ]
                                                        )
                row.pop("startXI", None)  # Remove original startXI key if it exists

            else:
                row["startxi"] = None

            if "substitutes" in row.keys():
                row["substitutes"] = convert_to_serializable([
                    {
                        k: (int(v) if k == "id" and v is not None else v)
                            for k, v in x["player"].items()
                            if k in ["id", "pos", "grid"]
                        }
                        for x in row["substitutes"]     
                    ]
                                                        )
            else:
                row["substitutes"] = None
            
            row["fixture"] = fixture_id
            current = datetime.now(ZoneInfo('Europe/Berlin'))
            row['created_at'] = current
            row['updated_at'] = current  
            return row
        
        def upsert_lineup(engine, data):
            metadata = MetaData()   
            lineups = Table(
                "apifootballlineups",
                metadata,
                Column("team", Integer),
                Column('fixture', BIGINT),
                Column("formation", Text), 
                Column("coach", JSON),
                Column("startxi", JSON),
                Column("substitutes", JSON),
                Column("created_at", TIMESTAMP(timezone=True), server_default=func.now()),
                Column("updated_at", TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()),
            )

            stmt = insert(lineups).values(**data)

            try:
                with engine.begin() as conn:
                    conn.execute(stmt)
            except Exception:
                time.sleep(2)
                with engine.begin() as conn:
                    conn.execute(stmt)     
        
        base_url = 'https://v3.football.api-sports.io/fixtures/lineups'

        headers = {
        'x-rapidapi-host': "v3.football.api-sports.io",
        'x-rapidapi-key': "api_key"
        }

        params = {
            'fixture': fixture_id
            }

        try:
            response = requests.get(base_url, headers=headers, params=params)
            if response.status_code == 200:
                time.sleep(65/300)
                data = response.json()
                if data["results"] == 0:
                    print(f"No lineups available for fixture {fixture_id}\n")
                    []
                else:
                    payload =  [parse_lineups(x) for x in data['response']]
                    for p in payload:
                        upsert_lineup(engine, p)
                    return payload
            else:
                print(f"Error fetching lineups fixture {fixture_id}: {response.status_code}")
                return []

        except Exception as e:
            print(f"Exception for lineups of fixture {fixture_id}: {e!s}")
            return []
    
        
    ldf = pd.DataFrame(leagues).explode("year")
    ldf = ldf[
        ldf.coverage.apply(lambda x: x["fixtures"]["lineups"])
        ].reset_index(drop=True).sort_values(["year", "league.id"], ascending = [False, True]).reset_index(drop=True)
    
    ldf["league_season"] = ldf["league.id"].astype(str) + ";" + ldf["year"].astype(str)
    updateFixtures["league_season"] = updateFixtures["tid"].astype(str) + ";" + updateFixtures["season"].astype(str)
    updateFixtures = updateFixtures[updateFixtures["league_season"].isin(ldf.league_season)].reset_index(drop=True)       
    fixtures_list = updateFixtures.id.unique().tolist()
    
    q = """
    SELECT id FROM apifootball af LEFT JOIN apifootballlineups fs ON af.id = fs.fixture
    WHERE fs.fixture is NULL
    AND af.start >= NOW() -INTERVAL '7 days' AND af.start <= NOW()
    """
    ids = pd.read_sql(q, engine)
    fixtures_list = [x for x in fixtures_list if x in ids.id.to_list()]
    for i, fixture_id in enumerate(fixtures_list):
        print(f"{i+1}/{len(fixtures_list)}:- Fixture ID: {fixture_id}")
        payload = fetch_lineups(fixture_id)
        if not payload:
            continue

def main():

    query = """
    SET TIMEZONE = "EUROPE/BERLIN";
    SELECT 
        a.id,a.start, a.home_team, a.away_team, a.tournament,a.tid,a.season, a.status, a.updated_at
    FROM public.apifootball a
    WHERE start >= now() - INTERVAL '14 days'
        AND start <= now() - INTERVAL '2 hours'
        AND status IN ('NS', '1H', '2H', 'HT', 'ET', 'INT', 'LIVE','P','BT', 'SUSP')
    ORDER by start
    """
    
    leagues = fetch_all_leagues()
    # leagues = pd.read_csv("assets/leagues.csv")
    updateFixtures = pd.read_sql(query, engine)
    # updateFixtures = pd.read_csv("assets/updateFixtures.csv")
    
    updateLeagues = updateFixtures[["tid", "season"]].drop_duplicates().rename(columns={"tid": "league"}).to_dict(orient='records')
    fixtures_list = updateFixtures.id.unique().tolist()
    updateFixtures.to_csv("assets/updateFixtures.csv", index=False)

    fixtures = update_fixtures(leagues)    
    update_statistics(updateFixtures, leagues)
    update_player_statistics(updateFixtures, leagues)
    fetch_all_lineups(updateFixtures, leagues)
    fetch_all_events(updateFixtures, leagues)

if __name__ == "__main__":
    main()
