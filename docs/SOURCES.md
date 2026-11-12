# Sources, permissions & as-of semantics (reviewed 2026-11-12)

| Provider | Data actually provided | Credentials/limitations | Intended use |
|---|---|---|---|
| BALLDONTLIE | Game schedule, player-game totals (PTS, REB, AST, 3PM), injury snapshot; advanced/team tracking according to tier | API key; **free** has games but **not player game stats**; ALL-STAR has PTS/REB/AST + injuries; GOAT for advanced and odds | Main licensed ingestion, stored with `fetched_at` |
| The Odds API | Upcoming NBA events and event-specific player props; dated market quotes | API key; historical snapshots are **paid**; regional and bookmaker coverage varies | Pre-match market snapshots, provider's `last_update` |
| NBA.com / `swar/nba_api` | Historical NBA public statistics wrappers | **NBA.com statistics terms prohibit their use in connection with gambling** | Research comparison ONLY; never ingest into this betting pipeline without written authorization |
| Official NBA injury reports | Player injury/availability report | Official report publication schedule; human/manual verification; NBA terms must be respected | Cross-check and provenance, not scraped automatically |

Official references:
- https://docs.balldontlie.io/
- https://www.balldontlie.io/terms.html
- https://the-odds-api.com/liveapi/guides/v4/
- https://the-odds-api.com/historical-odds-data/
- https://the-odds-api.com/terms-and-conditions.html
- https://www.nba.com/termsofuse
- https://official.nba.com/nba-injury-report-2026-27-season/
- https://github.com/swar/nba_api

## Data contracts

- `source`: provider identifier. `fetched_at`: system UTC timestamp. `quote_at`: timestamp actually reported by bookmaker market. These are not interchangeable.
- BDL stats are imported only for completed games; DNPs and missing values are NOT converted to zero outcomes.
- Odds are included only when the event's teams and start time match exactly one BDL game. No fuzzy substitution or inferred matchups.
- No code places a wager. Every displayed projection is a statistical estimate, not a guarantee.
- Retrospective snapshots must be as-of. Provider odds history cannot be reconstructed by overwriting a current quote's timestamp.
- BDL `player_injuries` reports injuries but absence from this list alone is not proof of fitness; manually verified availability evidence is required.
- The Odds API market data is allowed for analytical applications, but not resale as a standalone feed; review the agreement for intended deployment.

## Football

**football-data.org:** Fixtures and final match scores for supported competition/season; lineup coverage varies. `FOOTBALL_DATA_TOKEN` is required and the registered free plan is limited to around 10 requests/minute. The system uses this source only for research-only independent-Poisson baseline. **Required visible attribution:** “Football data provided by the Football-Data.org API”.

Football terms: https://www.football-data.org/about  
Football API docs: https://www.football-data.org/documentation/quickstart

Football source authorization should be checked for any public or commercial deployment. Its current research adapter uses explicit fixture IDs and kickoff dates and never labels its uncalibrated forecast as EV+.
