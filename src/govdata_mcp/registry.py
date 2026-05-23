from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


Method = Literal["GET", "POST", "OPTIONS"]
AuthKind = Literal[
    "none",
    "api_data_gov",
    "census",
    "bls",
    "eia",
    "fda",
    "fred",
    "ipums",
    "nrel",
    "noaa_token",
]
AuthLocation = Literal["query", "body", "header"]
AgencyStatus = Literal["active", "planned"]
EndpointStatus = Literal["active", "stale", "removed", "planned"]


@dataclass(frozen=True)
class Endpoint:
    id: str
    method: Method
    path: str
    description: str
    docs_url: str
    auth: AuthKind = "none"
    auth_location: AuthLocation = "query"
    auth_name: str | None = None
    demo_key: str | None = None
    default_query: dict[str, object] = field(default_factory=dict)
    rate_limit_note: str | None = None
    status: EndpointStatus = "active"
    status_note: str | None = None
    alternatives: tuple[str, ...] = ()
    redirect_policy: str | None = None


@dataclass(frozen=True)
class Agency:
    id: str
    name: str
    base_url: str
    docs_url: str
    description: str
    category: str
    status: AgencyStatus = "active"
    endpoints: dict[str, Endpoint] = field(default_factory=dict)
    rate_limit_note: str | None = None
    min_seconds_between_requests: float = 0.0
    passthrough_prefixes: tuple[str, ...] = ("/",)
    passthrough_methods: tuple[Method, ...] = ("GET", "POST", "OPTIONS")
    default_auth: AuthKind = "none"
    default_auth_location: AuthLocation = "query"
    default_auth_name: str | None = None
    default_demo_key: str | None = None


AUTH_ENV: dict[AuthKind, tuple[str, ...]] = {
    "none": (),
    "api_data_gov": ("API_DATA_GOV_KEY",),
    "census": ("CENSUS_API_KEY",),
    "bls": ("BLS_API_KEY",),
    "eia": ("EIA_API_KEY", "API_DATA_GOV_KEY"),
    "fda": ("FDA_API_KEY", "API_DATA_GOV_KEY"),
    "fred": ("FRED_API_KEY",),
    "ipums": ("IPUMS_API_KEY",),
    "nrel": ("NREL_API_KEY", "API_DATA_GOV_KEY"),
    "noaa_token": ("NOAA_TOKEN",),
}


def api_key_endpoint(
    id: str,
    method: Method,
    path: str,
    description: str,
    docs_url: str,
    *,
    auth: AuthKind = "api_data_gov",
    auth_location: AuthLocation = "query",
    auth_name: str = "api_key",
    demo_key: str | None = None,
    default_query: dict[str, object] | None = None,
) -> Endpoint:
    return Endpoint(
        id=id,
        method=method,
        path=path,
        description=description,
        docs_url=docs_url,
        auth=auth,
        auth_location=auth_location,
        auth_name=auth_name,
        demo_key=demo_key,
        default_query=default_query or {},
    )


FRED_DEFAULT_QUERY = {"file_type": "json"}
CONGRESS_DEFAULT_QUERY = {"format": "json"}


AGENCIES: dict[str, Agency] = {
    "datagov": Agency(
        id="datagov",
        name="Data.gov Catalog",
        base_url="https://catalog.data.gov",
        docs_url="https://resources.data.gov/catalog-api/",
        category="catalog",
        description="Dataset metadata catalog for federal, state, local, and tribal datasets.",
        endpoints={
            "search": Endpoint(
                id="search",
                method="GET",
                path="/search",
                description="Search catalog metadata by query, organization, topic, and spatial filters.",
                docs_url="https://resources.data.gov/catalog-api/#search-datasets",
            ),
            "organizations": Endpoint(
                id="organizations",
                method="GET",
                path="/api/organizations",
                description="List organizations publishing datasets in the catalog.",
                docs_url="https://resources.data.gov/catalog-api/#get-organizations",
            ),
            "keywords": Endpoint(
                id="keywords",
                method="GET",
                path="/api/keywords",
                description="List commonly used catalog keywords.",
                docs_url="https://resources.data.gov/catalog-api/#get-keywords",
            ),
        },
    ),
    "agriculture": Agency(
        id="agriculture",
        name="Department of Agriculture - FoodData Central",
        base_url="https://api.nal.usda.gov/fdc/v1",
        docs_url="https://fdc.nal.usda.gov/api-guide",
        category="agriculture-food",
        description="USDA FoodData Central nutrient and food data API.",
        default_auth="api_data_gov",
        default_auth_name="api_key",
        default_demo_key="DEMO_KEY",
        endpoints={
            "food": api_key_endpoint(
                id="food",
                method="GET",
                path="/food/{fdc_id}",
                description="Fetch details for one food item by FDC ID.",
                docs_url="https://fdc.nal.usda.gov/api-guide",
                demo_key="DEMO_KEY",
            ),
            "foods": api_key_endpoint(
                id="foods",
                method="POST",
                path="/foods",
                description="Fetch details for multiple food items.",
                docs_url="https://fdc.nal.usda.gov/api-guide",
                demo_key="DEMO_KEY",
            ),
            "foods_list": api_key_endpoint(
                id="foods_list",
                method="GET",
                path="/foods/list",
                description="Return a paged list of foods.",
                docs_url="https://fdc.nal.usda.gov/api-guide",
                demo_key="DEMO_KEY",
            ),
            "foods_search": api_key_endpoint(
                id="foods_search",
                method="POST",
                path="/foods/search",
                description="Search foods by keyword and filters.",
                docs_url="https://fdc.nal.usda.gov/api-guide",
                demo_key="DEMO_KEY",
            ),
        },
    ),
    "census": Agency(
        id="census",
        name="U.S. Census Bureau",
        base_url="https://api.census.gov",
        docs_url="https://www.census.gov/data/developers/guidance/api-user-guide.html",
        category="demographics",
        description="Raw statistical data from Census datasets, usually keyed by year, dataset, variables, and geography.",
        default_auth="census",
        default_auth_name="key",
        endpoints={
            "dataset": api_key_endpoint(
                id="dataset",
                method="GET",
                path="/data/{year}/{dataset}.json",
                description="Get dataset metadata.",
                docs_url="https://www.census.gov/data/developers/guidance/api-user-guide.html",
                auth="census",
                auth_name="key",
            ),
            "variables": api_key_endpoint(
                id="variables",
                method="GET",
                path="/data/{year}/{dataset}/variables.json",
                description="Get variables for a dataset.",
                docs_url="https://www.census.gov/data/developers/guidance/api-user-guide.html",
                auth="census",
                auth_name="key",
            ),
            "geography": api_key_endpoint(
                id="geography",
                method="GET",
                path="/data/{year}/{dataset}/geography.json",
                description="Get supported geography predicates for a dataset.",
                docs_url="https://www.census.gov/data/developers/guidance/api-user-guide.html",
                auth="census",
                auth_name="key",
            ),
            "data": api_key_endpoint(
                id="data",
                method="GET",
                path="/data/{year}/{dataset}",
                description="Fetch rows from a Census dataset.",
                docs_url="https://www.census.gov/data/developers/guidance/api-user-guide.html",
                auth="census",
                auth_name="key",
            ),
        },
    ),
    "bls": Agency(
        id="bls",
        name="Bureau of Labor Statistics",
        base_url="https://api.bls.gov",
        docs_url="https://www.bls.gov/developers/",
        category="labor",
        description="Published BLS time series from all BLS programs.",
        rate_limit_note="Registered users: 500 queries/day, 50 series/query, 20 years/query. Unregistered users: 25 queries/day, 25 series/query, 10 years/query.",
        endpoints={
            "timeseries": Endpoint(
                id="timeseries",
                method="POST",
                path="/publicAPI/v2/timeseries/data/",
                description="Fetch one or more BLS time series.",
                docs_url="https://www.bls.gov/developers/api_signature_v2.htm",
                auth="bls",
                auth_location="body",
                auth_name="registrationkey",
            ),
            "surveys": Endpoint(
                id="surveys",
                method="GET",
                path="/publicAPI/v2/surveys",
                description="List BLS surveys.",
                docs_url="https://www.bls.gov/developers/api_signature_v2.htm",
            ),
        },
    ),
    "usaspending": Agency(
        id="usaspending",
        name="USAspending.gov",
        base_url="https://api.usaspending.gov",
        docs_url="https://api.usaspending.gov/docs/endpoints",
        category="federal-spending",
        description="Federal award, obligation, agency, recipient, and disaster spending data.",
        endpoints={
            "awards_last_updated": Endpoint(
                id="awards_last_updated",
                method="GET",
                path="/api/v2/awards/last_updated/",
                description="Get the date awards data was last updated.",
                docs_url="https://api.usaspending.gov/docs/endpoints",
            ),
            "references_toptier_agencies": Endpoint(
                id="references_toptier_agencies",
                method="GET",
                path="/api/v2/references/toptier_agencies/",
                description="List top-tier federal agencies.",
                docs_url="https://api.usaspending.gov/docs/endpoints",
            ),
            "search_spending_by_award": Endpoint(
                id="search_spending_by_award",
                method="POST",
                path="/api/v2/search/spending_by_award/",
                description="Search filtered awards.",
                docs_url="https://api.usaspending.gov/docs/endpoints",
            ),
            "search_spending_by_category": Endpoint(
                id="search_spending_by_category",
                method="POST",
                path="/api/v2/search/spending_by_category/{category}/",
                description="Aggregate spending by a supported category path segment.",
                docs_url="https://api.usaspending.gov/docs/endpoints",
            ),
        },
    ),
    "commerce": Agency(
        id="commerce",
        name="Department of Commerce",
        base_url="https://api.commerce.gov",
        docs_url="https://www.commerce.gov/data-and-reports/developer-resources/commercegov-api",
        category="commerce-content",
        description="Commerce.gov content API for news, blogs, and image metadata.",
        default_auth="api_data_gov",
        default_auth_name="api_key",
        default_demo_key="DEMO_KEY",
        endpoints={
            "news": api_key_endpoint(
                id="news",
                method="GET",
                path="/api/news",
                description="Fetch Commerce news content.",
                docs_url="https://www.commerce.gov/data-and-reports/developer-resources/commercegov-api",
                demo_key="DEMO_KEY",
            ),
            "blogs": api_key_endpoint(
                id="blogs",
                method="GET",
                path="/api/blogs",
                description="Fetch Commerce blog content.",
                docs_url="https://www.commerce.gov/data-and-reports/developer-resources/commercegov-api",
                demo_key="DEMO_KEY",
            ),
            "image": api_key_endpoint(
                id="image",
                method="GET",
                path="/api/image",
                description="Fetch Commerce image content.",
                docs_url="https://www.commerce.gov/data-and-reports/developer-resources/commercegov-api",
                demo_key="DEMO_KEY",
            ),
        },
    ),
    "education": Agency(
        id="education",
        name="Department of Education - College Scorecard",
        base_url="https://api.data.gov/ed/collegescorecard/v1",
        docs_url="https://collegescorecard.ed.gov/data/api/",
        category="education",
        description="College Scorecard institution and field-of-study data.",
        default_auth="api_data_gov",
        default_auth_name="api_key",
        endpoints={
            "schools": api_key_endpoint(
                id="schools",
                method="GET",
                path="/schools",
                description="Query institution-level College Scorecard records.",
                docs_url="https://collegescorecard.ed.gov/data/api/",
            ),
            "fields_of_study": api_key_endpoint(
                id="fields_of_study",
                method="GET",
                path="/schools",
                description="Query College Scorecard field-of-study data via nested /schools program fields.",
                docs_url="https://collegescorecard.ed.gov/data/api/",
            ),
        },
    ),
    "justice": Agency(
        id="justice",
        name="Department of Justice - FBI Crime Data API",
        base_url="https://api.usa.gov/crime/fbi/cde",
        docs_url="https://www.justice.gov/developer",
        category="justice-crime",
        description="FBI Crime Data Explorer API for national, state, agency, and offense data.",
        default_auth="api_data_gov",
        default_auth_name="API_KEY",
        endpoints={
            "estimates_national": api_key_endpoint(
                id="estimates_national",
                method="GET",
                path="/estimates/national",
                description="Fetch national crime estimates.",
                docs_url="https://www.justice.gov/developer",
                auth_name="API_KEY",
            ),
            "estimates_states": api_key_endpoint(
                id="estimates_states",
                method="GET",
                path="/estimates/states/{state_abbr}",
                description="Fetch state crime estimates by postal abbreviation.",
                docs_url="https://www.justice.gov/developer",
                auth_name="API_KEY",
            ),
            "agencies": api_key_endpoint(
                id="agencies",
                method="GET",
                path="/agency/byStateAbbr/{state_abbr}",
                description="List FBI Crime Data Explorer agencies by state abbreviation.",
                docs_url="https://www.justice.gov/developer",
                auth_name="API_KEY",
            ),
            "summarized_national": api_key_endpoint(
                id="summarized_national",
                method="GET",
                path="/summarized/national/{offense}",
                description="Fetch monthly national FBI Crime Data Explorer offense summaries.",
                docs_url="https://github.com/fbi-cde/crime-data-api/blob/master/api_support_notes.md",
                auth_name="API_KEY",
            ),
            "summarized_state": api_key_endpoint(
                id="summarized_state",
                method="GET",
                path="/summarized/state/{state_abbr}/{offense}",
                description="Fetch monthly state FBI Crime Data Explorer offense summaries.",
                docs_url="https://github.com/fbi-cde/crime-data-api/blob/master/api_support_notes.md",
                auth_name="API_KEY",
            ),
            "summarized_agency": api_key_endpoint(
                id="summarized_agency",
                method="GET",
                path="/summarized/agency/{ori}/{offense}",
                description="Fetch monthly agency FBI Crime Data Explorer offense summaries by ORI.",
                docs_url="https://github.com/fbi-cde/crime-data-api/blob/master/api_support_notes.md",
                auth_name="API_KEY",
            ),
        },
    ),
    "justice_ncvs": Agency(
        id="justice_ncvs",
        name="Department of Justice - BJS National Crime Victimization Survey",
        base_url="https://api.ojp.gov/bjsdataset/v1",
        docs_url="https://bjs.ojp.gov/national-crime-victimization-survey-ncvs-api",
        category="justice-victimization",
        description="Bureau of Justice Statistics NCVS select datasets for personal and household victimization and population estimates.",
        default_auth="api_data_gov",
        default_auth_location="header",
        default_auth_name="X-Api-Key",
        endpoints={
            "personal_victimization": api_key_endpoint(
                id="personal_victimization",
                method="GET",
                path="/gcuy-rt5g.json",
                description="Query NCVS select personal violent and property victimization records.",
                docs_url="https://bjs.ojp.gov/national-crime-victimization-survey-ncvs-api",
                auth_location="header",
                auth_name="X-Api-Key",
            ),
            "personal_population": api_key_endpoint(
                id="personal_population",
                method="GET",
                path="/r4j4-fdwx.json",
                description="Query NCVS select personal population records used as analysis denominators.",
                docs_url="https://bjs.ojp.gov/national-crime-victimization-survey-ncvs-api",
                auth_location="header",
                auth_name="X-Api-Key",
            ),
            "household_victimization": api_key_endpoint(
                id="household_victimization",
                method="GET",
                path="/gkck-euys.json",
                description="Query NCVS select household property victimization records.",
                docs_url="https://bjs.ojp.gov/national-crime-victimization-survey-ncvs-api",
                auth_location="header",
                auth_name="X-Api-Key",
            ),
            "household_population": api_key_endpoint(
                id="household_population",
                method="GET",
                path="/ya4e-n9zp.json",
                description="Query NCVS select household population records used as analysis denominators.",
                docs_url="https://bjs.ojp.gov/national-crime-victimization-survey-ncvs-api",
                auth_location="header",
                auth_name="X-Api-Key",
            ),
        },
    ),
    "justice_crimesolutions": Agency(
        id="justice_crimesolutions",
        name="Department of Justice - CrimeSolutions",
        base_url="https://crimesolutions.ojp.gov",
        docs_url="https://www.justice.gov/developer",
        category="justice-evidence",
        description="NIJ CrimeSolutions rated program and practice evidence data for criminal justice, juvenile justice, and victim services interventions.",
        default_auth="api_data_gov",
        default_auth_location="header",
        default_auth_name="X-Api-Key",
        endpoints={
            "programs": api_key_endpoint(
                id="programs",
                method="GET",
                path="/topics/programs/content",
                description="Download CrimeSolutions rated program records.",
                docs_url="https://catalog.data.gov/dataset/crimesolutions-gov-programs",
                auth_location="header",
                auth_name="X-Api-Key",
                default_query={"all": ""},
            ),
            "practices": api_key_endpoint(
                id="practices",
                method="GET",
                path="/topics/practices/content",
                description="Download CrimeSolutions rated practice records.",
                docs_url="https://catalog.data.gov/dataset/crimesolutions-gov-practices",
                auth_location="header",
                auth_name="X-Api-Key",
                default_query={"all": ""},
            ),
        },
    ),
    "justice_fara": Agency(
        id="justice_fara",
        name="Department of Justice - FARA",
        base_url="https://efile.fara.gov",
        docs_url="https://efile.fara.gov/ords/fara/r/fara_ws/api/endpoints",
        category="justice-national-security",
        description="Foreign Agents Registration Act registrant, short-form, foreign-principal, and registration-document data.",
        rate_limit_note="FARA documents a throttle of 5 requests per 10 seconds; GovData spaces calls by 3 seconds.",
        min_seconds_between_requests=3.0,
        endpoints={
            "registrants_active": Endpoint(
                id="registrants_active",
                method="GET",
                path="/api/v1/Registrants/json/Active",
                description="List active FARA registrants.",
                docs_url="https://efile.fara.gov/ords/fara/r/fara_ws/api/endpoints",
            ),
            "registrants_terminated": Endpoint(
                id="registrants_terminated",
                method="GET",
                path="/api/v1/Registrants/json/Terminated",
                description="List terminated FARA registrants.",
                docs_url="https://efile.fara.gov/ords/fara/r/fara_ws/api/endpoints",
            ),
            "registrants_new": Endpoint(
                id="registrants_new",
                method="GET",
                path="/api/v1/Registrants/json/New",
                description="List new FARA registrants in a date range.",
                docs_url="https://efile.fara.gov/ords/fara/r/fara_ws/api/endpoints",
                redirect_policy="preserve_same_host_redirect_metadata",
            ),
            "registration_documents": Endpoint(
                id="registration_documents",
                method="GET",
                path="/api/v1/RegDocs/json/{registration_number}",
                description="List registration documents for a FARA registration number.",
                docs_url="https://efile.fara.gov/ords/fara/r/fara_ws/api/endpoints",
            ),
            "short_forms_active": Endpoint(
                id="short_forms_active",
                method="GET",
                path="/api/v1/ShortFormRegistrants/json/Active/{registration_number}",
                description="List active short-form registrants for a FARA registration number.",
                docs_url="https://efile.fara.gov/ords/fara/r/fara_ws/api/endpoints",
            ),
            "short_forms_terminated": Endpoint(
                id="short_forms_terminated",
                method="GET",
                path="/api/v1/ShortFormRegistrants/json/Terminated/{registration_number}",
                description="List terminated short-form registrants for a FARA registration number.",
                docs_url="https://efile.fara.gov/ords/fara/r/fara_ws/api/endpoints",
            ),
            "foreign_principals_active": Endpoint(
                id="foreign_principals_active",
                method="GET",
                path="/api/v1/ForeignPrincipals/json/Active/{registration_number}",
                description="List active foreign principals for a FARA registration number.",
                docs_url="https://efile.fara.gov/ords/fara/r/fara_ws/api/endpoints",
            ),
            "foreign_principals_terminated": Endpoint(
                id="foreign_principals_terminated",
                method="GET",
                path="/api/v1/ForeignPrincipals/json/Terminated/{registration_number}",
                description="List terminated foreign principals for a FARA registration number.",
                docs_url="https://efile.fara.gov/ords/fara/r/fara_ws/api/endpoints",
            ),
        },
    ),
    "treasury": Agency(
        id="treasury",
        name="Department of Treasury - Fiscal Data",
        base_url="https://api.fiscaldata.treasury.gov/services/api/fiscal_service",
        docs_url="https://fiscaldata.treasury.gov/about-us/",
        category="federal-finance",
        description="Treasury Fiscal Service federal finance APIs.",
        endpoints={
            "debt_to_penny": Endpoint(
                id="debt_to_penny",
                method="GET",
                path="/v2/accounting/od/debt_to_penny",
                description="Fetch Debt to the Penny records.",
                docs_url="https://fiscaldata.treasury.gov/about-us/",
            ),
            "rates_of_exchange": Endpoint(
                id="rates_of_exchange",
                method="GET",
                path="/v1/accounting/od/rates_of_exchange",
                description="Fetch Treasury reporting rates of exchange.",
                docs_url="https://fiscaldata.treasury.gov/about-us/",
            ),
        },
    ),
    "treasury_fiscaldata": Agency(
        id="treasury_fiscaldata",
        name="Treasury Fiscal Data",
        base_url="https://api.fiscaldata.treasury.gov/services/api/fiscal_service",
        docs_url="https://fiscaldata.treasury.gov/about-us/",
        category="federal-finance",
        description="Alias for Department of Treasury Fiscal Data APIs.",
        endpoints={
            "debt_to_penny": Endpoint(
                id="debt_to_penny",
                method="GET",
                path="/v2/accounting/od/debt_to_penny",
                description="Fetch Debt to the Penny records.",
                docs_url="https://fiscaldata.treasury.gov/about-us/",
            ),
        },
    ),
    "eia": Agency(
        id="eia",
        name="Energy Information Administration",
        base_url="https://api.eia.gov/v2",
        docs_url="https://www.eia.gov/opendata/documentation.php",
        category="energy",
        description="EIA API v2 data and metadata tree.",
        default_auth="eia",
        default_auth_name="api_key",
        endpoints={
            "metadata": api_key_endpoint(
                id="metadata",
                method="GET",
                path="/{route}",
                description="Fetch metadata for an EIA API v2 route.",
                docs_url="https://www.eia.gov/opendata/documentation.php",
                auth="eia",
            ),
            "data": api_key_endpoint(
                id="data",
                method="GET",
                path="/{route}/data",
                description="Fetch EIA API v2 data for a route.",
                docs_url="https://www.eia.gov/opendata/documentation.php",
                auth="eia",
            ),
            "seriesid": api_key_endpoint(
                id="seriesid",
                method="GET",
                path="/seriesid/{series_id}",
                description="Fetch an EIA series by legacy series ID.",
                docs_url="https://www.eia.gov/opendata/documentation.php",
                auth="eia",
            ),
        },
    ),
    "epa": Agency(
        id="epa",
        name="Environmental Protection Agency - ECHO",
        base_url="https://echodata.epa.gov/echo",
        docs_url="https://echo.epa.gov/tools/web-services",
        category="environment",
        description="EPA ECHO REST-like services for facility, compliance, and enforcement data.",
        endpoints={
            "all_media_facilities": Endpoint(
                id="all_media_facilities",
                method="GET",
                path="/rest_services.get_facilities",
                description="Search ECHO all-media regulated facilities.",
                docs_url="https://echo.epa.gov/tools/web-services",
                status="stale",
                status_note=(
                    "Provider GET requests currently return 404 for the registered all-media service; "
                    "use cwa_facilities or EPA ECHO data downloads until a working all-media REST URL is verified."
                ),
                alternatives=("epa.cwa_facilities", "epa.facility_report"),
            ),
            "cwa_facilities": Endpoint(
                id="cwa_facilities",
                method="GET",
                path="/cwa_rest_services.get_facilities",
                description="Search Clean Water Act facilities.",
                docs_url="https://echo.epa.gov/tools/web-services",
            ),
            "facility_report": Endpoint(
                id="facility_report",
                method="GET",
                path="/dfr_rest_services.get_dfr",
                description="Fetch an ECHO detailed facility report.",
                docs_url="https://echo.epa.gov/tools/web-services",
            ),
        },
    ),
    "fcc": Agency(
        id="fcc",
        name="Federal Communications Commission",
        base_url="https://geo.fcc.gov/api/census",
        docs_url="https://geo.fcc.gov/api/census/",
        category="communications-geography",
        description="FCC Area/Census API for census block and area lookups.",
        endpoints={
            "block_find": Endpoint(
                id="block_find",
                method="GET",
                path="/block/find",
                description="Find census block by latitude and longitude.",
                docs_url="https://geo.fcc.gov/api/census/",
            ),
            "area": Endpoint(
                id="area",
                method="GET",
                path="/area",
                description="Get area information for a geography request.",
                docs_url="https://geo.fcc.gov/api/census/",
            ),
        },
    ),
    "fdic": Agency(
        id="fdic",
        name="Federal Deposit Insurance Corporation - BankFind",
        base_url="https://api.fdic.gov/banks",
        docs_url="https://api.fdic.gov/banks/docs",
        category="banking",
        description="FDIC BankFind Suite public bank, branch, summary, financial, and failure data.",
        endpoints={
            "institutions": Endpoint("institutions", "GET", "/institutions", "Search FDIC institutions.", "https://api.fdic.gov/banks/docs"),
            "locations": Endpoint("locations", "GET", "/locations", "Search FDIC branch locations.", "https://api.fdic.gov/banks/docs"),
            "financials": Endpoint("financials", "GET", "/financials", "Query FDIC financial data.", "https://api.fdic.gov/banks/docs"),
            "summary": Endpoint("summary", "GET", "/summary", "Query FDIC summary data.", "https://api.fdic.gov/banks/docs"),
            "failures": Endpoint("failures", "GET", "/failures", "Query failed bank data.", "https://api.fdic.gov/banks/docs"),
        },
    ),
    "fec": Agency(
        id="fec",
        name="Federal Election Commission",
        base_url="https://api.open.fec.gov/v1",
        docs_url="https://api.open.fec.gov/developers/",
        category="campaign-finance",
        description="Federal campaign finance data from OpenFEC.",
        default_auth="api_data_gov",
        default_auth_name="api_key",
        default_demo_key="DEMO_KEY",
        endpoints={
            "candidates": api_key_endpoint("candidates", "GET", "/candidates", "Search federal candidates.", "https://api.open.fec.gov/developers/", demo_key="DEMO_KEY"),
            "committees": api_key_endpoint("committees", "GET", "/committees", "Search political committees.", "https://api.open.fec.gov/developers/", demo_key="DEMO_KEY"),
            "schedule_a": api_key_endpoint("schedule_a", "GET", "/schedules/schedule_a", "Search itemized receipts.", "https://api.open.fec.gov/developers/", demo_key="DEMO_KEY"),
            "schedule_b": api_key_endpoint("schedule_b", "GET", "/schedules/schedule_b", "Search itemized disbursements.", "https://api.open.fec.gov/developers/", demo_key="DEMO_KEY"),
            "filings": api_key_endpoint("filings", "GET", "/filings", "Search FEC filings.", "https://api.open.fec.gov/developers/", demo_key="DEMO_KEY"),
            "elections": api_key_endpoint("elections", "GET", "/elections/", "Search election metadata using office values president, senate, or house.", "https://api.open.fec.gov/developers/", demo_key="DEMO_KEY"),
        },
    ),
    "ftc": Agency(
        id="ftc",
        name="Federal Trade Commission",
        base_url="https://api.ftc.gov",
        docs_url="https://www.ftc.gov/developer/",
        category="consumer-protection",
        description="FTC Do Not Call complaints and HSR early termination notices APIs.",
        default_auth="api_data_gov",
        default_auth_name="api_key",
        endpoints={
            "dnc_complaints": api_key_endpoint(
                id="dnc_complaints",
                method="GET",
                path="/v0/dnc-complaints",
                description="List Do Not Call complaint records.",
                docs_url="https://www.ftc.gov/node/27926",
            ),
            "dnc_complaint": api_key_endpoint(
                id="dnc_complaint",
                method="GET",
                path="/v0/dnc-complaints/{id}",
                description="Fetch one Do Not Call complaint record.",
                docs_url="https://www.ftc.gov/node/27926",
            ),
            "hsr_early_termination_notices": api_key_endpoint(
                id="hsr_early_termination_notices",
                method="GET",
                path="/v0/hsr-early-termination-notices",
                description="List HSR early termination notices.",
                docs_url="https://www.ftc.gov/developer/",
            ),
        },
    ),
    "fda": Agency(
        id="fda",
        name="Food and Drug Administration - openFDA",
        base_url="https://api.fda.gov",
        docs_url="https://open.fda.gov/apis/",
        category="health-regulatory",
        description="openFDA drug, device, and food datasets.",
        default_auth="fda",
        default_auth_name="api_key",
        endpoints={
            "drug_label": api_key_endpoint("drug_label", "GET", "/drug/label.json", "Query drug labeling records.", "https://open.fda.gov/apis/", auth="fda"),
            "drug_event": api_key_endpoint("drug_event", "GET", "/drug/event.json", "Query drug adverse event reports.", "https://open.fda.gov/apis/", auth="fda"),
            "drug_enforcement": api_key_endpoint("drug_enforcement", "GET", "/drug/enforcement.json", "Query drug enforcement/recall data.", "https://open.fda.gov/apis/", auth="fda"),
            "device_event": api_key_endpoint("device_event", "GET", "/device/event.json", "Query device adverse event reports.", "https://open.fda.gov/apis/", auth="fda"),
            "food_enforcement": api_key_endpoint("food_enforcement", "GET", "/food/enforcement.json", "Query food enforcement/recall data.", "https://open.fda.gov/apis/", auth="fda"),
        },
    ),
    "gsa": Agency(
        id="gsa",
        name="General Services Administration",
        base_url="https://open.gsa.gov",
        docs_url="https://open.gsa.gov/api/",
        category="government-services",
        description="GSA API directory and GSA-operated public service APIs.",
        endpoints={
            "api_directory": Endpoint("api_directory", "GET", "/api/", "Fetch the GSA API directory page.", "https://open.gsa.gov/api/"),
        },
    ),
    "govinfo": Agency(
        id="govinfo",
        name="Government Publishing Office - govinfo",
        base_url="https://api.govinfo.gov",
        docs_url="https://api.govinfo.gov/docs/",
        category="federal-publications",
        description="Metadata and content for official publications from all three branches of the federal government.",
        default_auth="api_data_gov",
        default_auth_name="api_key",
        default_demo_key="DEMO_KEY",
        endpoints={
            "collections": api_key_endpoint("collections", "GET", "/collections/{collection}/{start_date}", "List packages added or modified in a collection starting at an ISO timestamp, using offsetMark cursor paging.", "https://www.govinfo.gov/features/api", demo_key="DEMO_KEY", default_query={"pageSize": 5, "offsetMark": "*"}),
            "package_summary": api_key_endpoint("package_summary", "GET", "/packages/{package_id}/summary", "Get package-level summary metadata.", "https://www.govinfo.gov/features/api", demo_key="DEMO_KEY"),
            "package_granules": api_key_endpoint("package_granules", "GET", "/packages/{package_id}/granules", "List granules inside a package.", "https://www.govinfo.gov/features/api", demo_key="DEMO_KEY", default_query={"pageSize": 5, "offsetMark": "*"}),
            "search": api_key_endpoint("search", "POST", "/search", "Search govinfo packages and granules.", "https://www.govinfo.gov/features/search-service-overview", demo_key="DEMO_KEY"),
        },
    ),
    "loc": Agency(
        id="loc",
        name="Library of Congress - Congress.gov",
        base_url="https://api.congress.gov/v3",
        docs_url="https://www.loc.gov/apis/additional-apis/congress-dot-gov-api/",
        category="legislative",
        description="Congress.gov v3 API for bills, members, committees, hearings, and nominations; examples request JSON output.",
        default_auth="api_data_gov",
        default_auth_location="header",
        default_auth_name="x-api-key",
        endpoints={
            "bill": api_key_endpoint("bill", "GET", "/bill", "List bills.", "https://api.congress.gov/", auth_location="header", auth_name="x-api-key", default_query=CONGRESS_DEFAULT_QUERY),
            "bill_detail": api_key_endpoint("bill_detail", "GET", "/bill/{congress}/{bill_type}/{bill_number}", "Fetch one bill.", "https://api.congress.gov/", auth_location="header", auth_name="x-api-key", default_query=CONGRESS_DEFAULT_QUERY),
            "member": api_key_endpoint("member", "GET", "/member", "List members of Congress.", "https://api.congress.gov/", auth_location="header", auth_name="x-api-key", default_query=CONGRESS_DEFAULT_QUERY),
            "committee": api_key_endpoint("committee", "GET", "/committee", "List committees.", "https://api.congress.gov/", auth_location="header", auth_name="x-api-key", default_query=CONGRESS_DEFAULT_QUERY),
            "hearing": api_key_endpoint("hearing", "GET", "/hearing", "List hearings.", "https://api.congress.gov/", auth_location="header", auth_name="x-api-key", default_query=CONGRESS_DEFAULT_QUERY),
            "nomination": api_key_endpoint("nomination", "GET", "/nomination", "List nominations.", "https://api.congress.gov/", auth_location="header", auth_name="x-api-key", default_query=CONGRESS_DEFAULT_QUERY),
        },
    ),
    "nih": Agency(
        id="nih",
        name="National Institutes of Health - RePORTER",
        base_url="https://api.reporter.nih.gov",
        docs_url="https://api.reporter.nih.gov/",
        category="health-science",
        description="Search federal scientific awards and related publications.",
        rate_limit_note="NIH recommends no more than one URL request per second and large jobs outside peak hours; GovData spaces calls by 3 seconds.",
        min_seconds_between_requests=3.0,
        endpoints={
            "projects_search": Endpoint("projects_search", "POST", "/v2/projects/search", "Search NIH-funded and related federal projects.", "https://api.reporter.nih.gov/"),
            "publications_search": Endpoint("publications_search", "POST", "/v2/publications/search", "Search publications associated with NIH projects.", "https://api.reporter.nih.gov/"),
        },
    ),
    "nih_reporter": Agency(
        id="nih_reporter",
        name="NIH RePORTER",
        base_url="https://api.reporter.nih.gov",
        docs_url="https://api.reporter.nih.gov/",
        category="health-science",
        description="Alias for NIH RePORTER projects and publications APIs.",
        rate_limit_note="NIH recommends no more than one URL request per second and large jobs outside peak hours; GovData spaces calls by 3 seconds.",
        min_seconds_between_requests=3.0,
        endpoints={
            "projects_search": Endpoint("projects_search", "POST", "/v2/projects/search", "Search NIH-funded and related federal projects.", "https://api.reporter.nih.gov/"),
            "publications_search": Endpoint("publications_search", "POST", "/v2/publications/search", "Search publications associated with NIH projects.", "https://api.reporter.nih.gov/"),
        },
    ),
    "nrel": Agency(
        id="nrel",
        name="National Laboratory of the Rockies Developer Network",
        base_url="https://developer.nlr.gov/api",
        docs_url="https://developer.nlr.gov/docs/",
        category="energy",
        description="NLR renewable energy and transportation APIs, including migrated NREL Developer Network routes.",
        default_auth="nrel",
        default_auth_name="api_key",
        default_demo_key="DEMO_KEY",
        endpoints={
            "alt_fuel_stations": api_key_endpoint("alt_fuel_stations", "GET", "/alt-fuel-stations/v1.json", "Search alternative fuel stations.", "https://developer.nlr.gov/docs/transportation/alt-fuel-stations-v1/", auth="nrel", demo_key="DEMO_KEY"),
            "alt_fuel_nearest": api_key_endpoint("alt_fuel_nearest", "GET", "/alt-fuel-stations/v1/nearest.json", "Find nearest alternative fuel stations.", "https://developer.nlr.gov/docs/transportation/alt-fuel-stations-v1/", auth="nrel", demo_key="DEMO_KEY"),
            "pvwatts_v8": api_key_endpoint("pvwatts_v8", "GET", "/pvwatts/v8.json", "Run PVWatts v8 solar performance model.", "https://developer.nlr.gov/docs/solar/pvwatts/v8/", auth="nrel", demo_key="DEMO_KEY"),
        },
    ),
    "fred": Agency(
        id="fred",
        name="Federal Reserve Economic Data",
        base_url="https://api.stlouisfed.org/fred",
        docs_url="https://fred.stlouisfed.org/docs/api/fred/v2/index.html",
        category="economic-data",
        description="FRED and ALFRED economic data series, releases, categories, and observations.",
        default_auth="fred",
        default_auth_name="api_key",
        endpoints={
            "series_search": api_key_endpoint("series_search", "GET", "/series/search", "Search FRED economic data series.", "https://fred.stlouisfed.org/docs/api/fred/series/series_search.html", auth="fred", default_query=FRED_DEFAULT_QUERY),
            "series": api_key_endpoint("series", "GET", "/series", "Fetch FRED series metadata.", "https://fred.stlouisfed.org/docs/api/fred/series.html", auth="fred", default_query=FRED_DEFAULT_QUERY),
            "series_observations": api_key_endpoint("series_observations", "GET", "/series/observations", "Fetch observations for a FRED series.", "https://fred.stlouisfed.org/docs/api/fred/series_observations.html", auth="fred", default_query=FRED_DEFAULT_QUERY),
            "category": api_key_endpoint("category", "GET", "/category", "Fetch a FRED category.", "https://fred.stlouisfed.org/docs/api/fred/category.html", auth="fred", default_query=FRED_DEFAULT_QUERY),
            "category_children": api_key_endpoint("category_children", "GET", "/category/children", "Fetch child categories.", "https://fred.stlouisfed.org/docs/api/fred/category_children.html", auth="fred", default_query=FRED_DEFAULT_QUERY),
            "releases": api_key_endpoint("releases", "GET", "/releases", "List FRED releases.", "https://fred.stlouisfed.org/docs/api/fred/releases.html", auth="fred", default_query=FRED_DEFAULT_QUERY),
            "release": api_key_endpoint("release", "GET", "/release", "Fetch one FRED release.", "https://fred.stlouisfed.org/docs/api/fred/release.html", auth="fred", default_query=FRED_DEFAULT_QUERY),
            "release_series": api_key_endpoint("release_series", "GET", "/release/series", "Fetch series for a release.", "https://fred.stlouisfed.org/docs/api/fred/release_series.html", auth="fred", default_query=FRED_DEFAULT_QUERY),
            "v2_release_observations": api_key_endpoint("v2_release_observations", "GET", "/v2/release/observations", "Fetch bulk observations for all series in a release using FRED API v2.", "https://fred.stlouisfed.org/docs/api/fred/v2/index.html", auth="fred", default_query=FRED_DEFAULT_QUERY),
        },
    ),
    "datausa": Agency(
        id="datausa",
        name="Data USA",
        base_url="https://api.datausa.io/tesseract",
        docs_url="https://datausa.io/about/api/",
        category="demographics",
        description="Aggregated demographic and economic data from Census and other public sources.",
        endpoints={
            "data": Endpoint("data", "GET", "/data.jsonrecords", "Query Data USA Tesseract records.", "https://datausa.io/about/api/"),
            "search": Endpoint("search", "GET", "/cubes", "List Data USA Tesseract cubes for dataset discovery.", "https://datausa.io/about/api/"),
        },
    ),
    "ipums": Agency(
        id="ipums",
        name="IPUMS",
        base_url="https://api.ipums.org",
        docs_url="https://developer.ipums.org/docs/v2/",
        category="harmonized-extracts",
        description=(
            "IPUMS extract, metadata, and download APIs for harmonized microdata, "
            "aggregate, and spatial collections. Prefer for downloadable ACS, CPS, "
            "ATUS, NHIS, DHS, and related survey extracts when IPUMS_API_KEY is configured."
        ),
        default_auth="ipums",
        default_auth_location="header",
        default_auth_name="Authorization",
        rate_limit_note="IPUMS API keys are rate limited by IPUMS; current docs state 100 requests per minute.",
        passthrough_prefixes=("/extracts", "/metadata", "/downloads", "/supplemental-data"),
        endpoints={
            "extracts": Endpoint(
                id="extracts",
                method="GET",
                path="/extracts",
                description="List recent IPUMS extract requests for a collection.",
                docs_url="https://developer.ipums.org/docs/v2/workflows/create_extracts/microdata/",
                auth="ipums",
                auth_location="header",
                auth_name="Authorization",
                default_query={"version": 2},
            ),
            "extract": Endpoint(
                id="extract",
                method="GET",
                path="/extracts/{extract_number}",
                description="Fetch status and downloadLinks for one IPUMS extract.",
                docs_url="https://developer.ipums.org/docs/v2/workflows/create_extracts/microdata/",
                auth="ipums",
                auth_location="header",
                auth_name="Authorization",
                default_query={"version": 2},
            ),
            "create_extract": Endpoint(
                id="create_extract",
                method="POST",
                path="/extracts",
                description="Submit an asynchronous IPUMS extract request for a supported collection.",
                docs_url="https://developer.ipums.org/docs/v2/workflows/create_extracts/microdata/",
                auth="ipums",
                auth_location="header",
                auth_name="Authorization",
                default_query={"version": 2},
            ),
            "metadata_datasets": Endpoint(
                id="metadata_datasets",
                method="GET",
                path="/metadata/datasets",
                description="List datasets for IPUMS NHGIS or IHGIS metadata discovery.",
                docs_url="https://developer.ipums.org/docs/v2/workflows/explore_metadata/nhgis/datasets/",
                auth="ipums",
                auth_location="header",
                auth_name="Authorization",
                default_query={"version": 2},
            ),
            "metadata_dataset": Endpoint(
                id="metadata_dataset",
                method="GET",
                path="/metadata/datasets/{dataset_name}",
                description="Fetch one IPUMS NHGIS or IHGIS dataset metadata record.",
                docs_url="https://developer.ipums.org/docs/v2/workflows/explore_metadata/nhgis/datasets/",
                auth="ipums",
                auth_location="header",
                auth_name="Authorization",
                default_query={"version": 2},
            ),
            "metadata_data_tables": Endpoint(
                id="metadata_data_tables",
                method="GET",
                path="/metadata/data_tables",
                description="Search or list IPUMS NHGIS or IHGIS data table metadata.",
                docs_url="https://developer.ipums.org/docs/v2/workflows/explore_metadata/nhgis/datasets/",
                auth="ipums",
                auth_location="header",
                auth_name="Authorization",
                default_query={"version": 2},
            ),
            "metadata_shapefiles": Endpoint(
                id="metadata_shapefiles",
                method="GET",
                path="/metadata/shapefiles",
                description="List IPUMS NHGIS or IHGIS shapefile metadata.",
                docs_url="https://developer.ipums.org/docs/v2/workflows/explore_metadata/nhgis/shapefiles/",
                auth="ipums",
                auth_location="header",
                auth_name="Authorization",
                default_query={"version": 2},
            ),
            "metadata_time_series_tables": Endpoint(
                id="metadata_time_series_tables",
                method="GET",
                path="/metadata/time_series_tables",
                description="List IPUMS NHGIS or IHGIS time series table metadata.",
                docs_url="https://developer.ipums.org/docs/v2/workflows/explore_metadata/nhgis/time_series_tables/",
                auth="ipums",
                auth_location="header",
                auth_name="Authorization",
                default_query={"version": 2},
            ),
            "download": Endpoint(
                id="download",
                method="GET",
                path="/downloads/{download_path}",
                description="Fetch an IPUMS downloadLink path returned by a completed extract.",
                docs_url="https://developer.ipums.org/docs/v2/workflows/create_extracts/microdata/",
                auth="ipums",
                auth_location="header",
                auth_name="Authorization",
            ),
            "supplemental_data": Endpoint(
                id="supplemental_data",
                method="GET",
                path="/supplemental-data/{supplemental_path}",
                description="Fetch IPUMS supplemental data paths such as NHGIS crosswalk assets.",
                docs_url="https://developer.ipums.org/docs/v2/workflows/access_supplemental_data/",
                auth="ipums",
                auth_location="header",
                auth_name="Authorization",
            ),
        },
    ),
}


def list_agencies(include_planned: bool = True) -> list[dict[str, object]]:
    agencies = []
    for agency in AGENCIES.values():
        if agency.status == "planned" and not include_planned:
            continue
        agencies.append(agency_summary(agency))
    return agencies


def agency_summary(agency: Agency) -> dict[str, object]:
    return {
        "id": agency.id,
        "name": agency.name,
        "category": agency.category,
        "status": agency.status,
        "base_url": agency.base_url,
        "docs_url": agency.docs_url,
        "description": agency.description,
        "rate_limit_note": agency.rate_limit_note,
        "passthrough_prefixes": list(agency.passthrough_prefixes),
        "passthrough_methods": list(agency.passthrough_methods),
        "default_auth": agency.default_auth,
        "endpoints": [
            {
                "id": endpoint.id,
                "method": endpoint.method,
                "path": endpoint.path,
                "description": endpoint.description,
                "docs_url": endpoint.docs_url,
                "auth": endpoint.auth,
                "status": endpoint.status,
                "status_note": endpoint.status_note,
                "alternatives": list(endpoint.alternatives),
                "redirect_policy": endpoint.redirect_policy,
            }
            for endpoint in agency.endpoints.values()
        ],
    }


def get_agency(agency_id: str) -> Agency:
    try:
        return AGENCIES[agency_id]
    except KeyError as exc:
        raise KeyError(f"Unknown agency_id '{agency_id}'. Use govdata_list_agencies first.") from exc


def get_endpoint(agency: Agency, endpoint_id: str) -> Endpoint:
    if agency.status != "active":
        raise KeyError(f"Agency '{agency.id}' is planned but not implemented.")
    try:
        endpoint = agency.endpoints[endpoint_id]
    except KeyError as exc:
        raise KeyError(f"Unknown endpoint_id '{endpoint_id}' for agency '{agency.id}'.") from exc
    if endpoint.status != "active":
        note = f" {endpoint.status_note}" if endpoint.status_note else ""
        raise KeyError(
            f"Endpoint '{agency.id}.{endpoint.id}' is {endpoint.status} and cannot be executed.{note}"
        )
    return endpoint
