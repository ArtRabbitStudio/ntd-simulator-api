import json
import pandas
import hashlib
import logging

from datetime import datetime
from flask import Flask, Response, request, abort
from flask_cors import CORS, cross_origin

import gcs
from sth_simulation.helsim_RUN import STH_Simulation
from trachoma.trachoma_simulations import Trachoma_Simulation

################################################
###### CONSTANTS FOR FILE & STORAGE PATHS ######
################################################

bucket_name = 'ntd-disease-simulator-data'
gs_prefix = "gs:/"
https_prefix = "https://storage.googleapis.com"

parameter_file_names = {
    'sth-roundworm': "AscarisParameters_moderate.txt",
    'sth-whipworm': "TrichurisParameters_moderate.txt",
    'sth-hookworm': "HookwormParameters_moderate.txt",
    'sch-mansoni': "SCH_MansoniParameters.txt"
}

file_name_disease_abbreviations = {
    'sth-roundworm': "Asc",
    'sth-whipworm': "Tri",
    'sth-hookworm': "Hook",
    'sch-mansoni': "Man",
    'trachoma': "Trac",
}

###############################
###### UTILITY FUNCTIONS ######
###############################

def generate_summary( InCSVPath, OutJsonPath ):
    prevalence = pandas.read_csv( InCSVPath )
    summary = pandas.DataFrame( {
        'median': prevalence.iloc[:, 2:].median(),
        'lower': prevalence.iloc[:, 2:].quantile(0.05),
        'upper': prevalence.iloc[:, 2:].quantile(0.95)
    }).to_json()
    gcs.write_string_to_file( summary, OutJsonPath )

#######################
###### FLASK APP ######
#######################

# setup
app = Flask(__name__)
cors = CORS( app, resources = { r"/run": { "origins": "*" } } ) # TODO FIXME to right origin
app.config[ 'CORS_HEADERS' ] = 'content-type'

# logging
app.logger.setLevel( logging.INFO )

# gunicorn logging if run there under WSGI
if __name__ != '__main__':
    gunicorn_logger = logging.getLogger( 'gunicorn.error' )
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel( gunicorn_logger.level )

# routes
@app.route('/')
def root():
    return Response( '👋\n', mimetype = 'text/plain' )

@app.route( '/run', methods = [ 'POST', 'OPTIONS' ] )
@cross_origin( origin = "*", headers = [ 'content-type' ] )
def run():

    print_function = app.logger.info if app.logger is not None else print

    # read in configuration from POST
    request_data_str = str( request.data, 'UTF-8' )
    request_hash = hashlib.sha256( request_data_str.encode( 'UTF-8' ) ).hexdigest()[ 0:24 ]

    # snag necessary vars
    for key in [ 'disease', 'iu', 'runs' ]:
        if not key in request.json:
            print_function( f"request data is missing key: {key}" )
            abort( 400 )

    disease = request.json[ 'disease' ]

    if disease == 'trachoma':
        return run_trachoma( request_hash, request.json )

    if not request.json[ 'mdaData' ]:
        print_function( f"request data is missing key 'mdaData'" )
        abort( 400 )

    if not disease in parameter_file_names or not disease in file_name_disease_abbreviations:
        print_function( f"request data specifies unknown disease: {disease}" )
        abort( 400 )

    return run_sth( request_hash, request.json )

################################################################
###### STH/SCH: roundworm / whipworm / hookwork / mansoni ######
################################################################
def run_sth( request_hash, params ):

    disease = params[ 'disease' ]

    try:

        iu = params[ 'iu' ]
        country = iu[ 0:3 ]
        iu_id = iu[ 3: ]
        column_names = params[ 'mdaData' ][ 0 ]
        mda_data = params[ 'mdaData' ][ 1: ]
        numReps = 200 if params[ 'runs' ] > 200 else params[ 'runs' ]

        paramFileName = parameter_file_names[ disease ]
        file_abbrev = file_name_disease_abbreviations[ disease ]

    except Exception as e:

        return json.dumps( {
            'status': False,
            'msg': str( e )
        } )

    ############################################################################

    # set up all the file paths
    source_data_path_root = f"diseases/{disease}/source-data" if disease == 'sch-mansoni' else f"diseases/{disease}/source-data-redesign2021" # TODO FIXME
    source_data_gcs_path_root = f"/{bucket_name}/{source_data_path_root}"

    output_data_path_root = f"diseases/{disease}/output-data"
    output_data_gcs_path_root = f"/{bucket_name}/{output_data_path_root}"

    OutputDirectoryPath = f"{output_data_path_root}/{country}/{iu}/{request_hash}"
    OutputDirectoryGsPath = f"/{bucket_name}/{OutputDirectoryPath}"

    ############################################################################

    # Input MDA file to be generated from input
    MDAFilePath = f"{OutputDirectoryPath}/InputMDA-{request_hash}.csv"
    GcsMDAFilePath = f"{gs_prefix}/{bucket_name}/{MDAFilePath}"

    # RK CSV to be loaded from cloud storage
    GcsRkFilePath = f"{gs_prefix}{source_data_gcs_path_root}/{country}/{iu}/Input_Rk_{file_abbrev}_{iu}.csv"
    HttpsRkFilePath = f"{https_prefix}{source_data_gcs_path_root}/{country}/{iu}/Input_Rk_{file_abbrev}_{iu}.csv"
    InSimFilePath = f"{source_data_path_root}/{country}/{iu}/{file_abbrev}_{iu}.p"

    # PrevKKSAC CSV to be generated by model
    PrevKKSACFileName = f"OutputPrevKKSAC-{file_abbrev}-{iu}-{request_hash}.csv"
    PrevKKSACBlobPath = f"{OutputDirectoryPath}/{PrevKKSACFileName}"
    GcsPrevKKSACFilePath = f"{gs_prefix}{OutputDirectoryGsPath}/{PrevKKSACFileName}"
    HttpsPrevKKSACFilePath = f"{https_prefix}{OutputDirectoryGsPath}/{PrevKKSACFileName}"

    # PrevKKSAC summary to be generated below
    PrevKKSACSummaryFileName = PrevKKSACFileName[:-4] + "-summary.json"
    GcsPrevKKSACSummaryFilePath = f"{OutputDirectoryPath}/{PrevKKSACSummaryFileName}"
    HttpsPrevKKSACSummaryFilePath = f"{https_prefix}{OutputDirectoryGsPath}/{PrevKKSACSummaryFileName}"

    # PrevMHISAC CSV to be generated by model
    PrevMHISACFileName = f"OutputPrevMHISAC-{file_abbrev}-{iu}-{request_hash}.csv"
    PrevMHISACBlobPath = f"{OutputDirectoryPath}/{PrevMHISACFileName}"
    GcsPrevMHISACFilePath = f"{gs_prefix}{OutputDirectoryGsPath}/{PrevMHISACFileName}"
    HttpsPrevMHISACFilePath = f"{https_prefix}{OutputDirectoryGsPath}/{PrevMHISACFileName}"

    # PrevMHISAC summary to be generated below
    PrevMHISACSummaryFileName = PrevMHISACFileName[:-4] + "-summary.json"
    GcsPrevMHISACSummaryFilePath = f"{OutputDirectoryPath}/{PrevMHISACSummaryFileName}"
    HttpsPrevMHISACSummaryFilePath = f"{https_prefix}{OutputDirectoryGsPath}/{PrevMHISACSummaryFileName}"

    # HistoricalKKSAC prevalence CSV to be loaded from cloud storage
    HistoricalKKSACPrevFileName = f"PrevKKSAC{file_abbrev}_{iu}.csv"
    GcsHistoricalKKSACPrevFilePath = f"{gs_prefix}{source_data_gcs_path_root}/{country}/{iu}/{HistoricalKKSACPrevFileName}"
    HttpsHistoricalKKSACPrevFilePath = f"{https_prefix}{source_data_gcs_path_root}/{country}/{iu}/{HistoricalKKSACPrevFileName}"

    # HistoricalKKSAC prevalence summary to be generated below
    HistoricalKKSACPrevSummaryFileName = f"HistoricalKKSACPrev-{iu}-{request_hash}-summary.json"
    GcsHistoricalKKSACPrevSummaryFilePath = f"{OutputDirectoryPath}/{HistoricalKKSACPrevSummaryFileName}"
    HttpsHistoricalKKSACPrevSummaryFilePath = f"{https_prefix}{OutputDirectoryGsPath}/{HistoricalKKSACPrevSummaryFileName}"

    # HistoricalMHISAC prevalence CSV to be loaded from cloud storage
    HistoricalMHISACPrevFileName = f"PrevMHISAC{file_abbrev}_{iu}.csv"
    GcsHistoricalMHISACPrevFilePath = f"{gs_prefix}{source_data_gcs_path_root}/{country}/{iu}/{HistoricalMHISACPrevFileName}"
    HttpsHistoricalMHISACPrevFilePath = f"{https_prefix}{source_data_gcs_path_root}/{country}/{iu}/{HistoricalMHISACPrevFileName}"

    # HistoricalMHISAC prevalence summary to be generated below
    HistoricalMHISACPrevSummaryFileName = f"HistoricalMHISACPrev-{iu}-{request_hash}-summary.json"
    GcsHistoricalMHISACPrevSummaryFilePath = f"{OutputDirectoryPath}/{HistoricalMHISACPrevSummaryFileName}"
    HttpsHistoricalMHISACPrevSummaryFilePath = f"{https_prefix}{OutputDirectoryGsPath}/{HistoricalMHISACPrevSummaryFileName}"

    ############################################################################

    # stick it all in a dict to save to storage and send to client on success
    Result = {
        'status': True,
        'isNewSimulation': False,
        'historicalKKSACDataUrl': HttpsHistoricalKKSACPrevFilePath,
        'historicalKKSACSummaryUrl': HttpsHistoricalKKSACPrevSummaryFilePath,
        'historicalMHISACDataUrl': HttpsHistoricalMHISACPrevFilePath,
        'historicalMHISACSummaryUrl': HttpsHistoricalMHISACPrevSummaryFilePath,
        'futureKKSACDataUrl': HttpsPrevKKSACFilePath,
        'futureKKSACSummaryUrl': HttpsPrevKKSACSummaryFilePath,
        'futureMHISACDataUrl': HttpsPrevMHISACFilePath,
        'futureMHISACSummaryUrl': HttpsPrevMHISACSummaryFilePath,
    }

    ############################################################################

    # convert the incoming scenario mdaData to a CSV and write it to GCS
    try:

        pandas.DataFrame(
            params[ 'mdaData' ][ 1: ],
            columns = params[ 'mdaData' ][ 0 ]
        ).to_csv(
            GcsMDAFilePath,
            index = None
        )

    except Exception as e:

        return json.dumps( {
            'status': False,
            'msg': str( e )
        } )

    ############################################################################

    # run the scenario, if its output hasn't already been written to cloud storage
    if (
        ( not ( gcs.blob_exists( PrevKKSACBlobPath ) ) )
        or
        ( not ( gcs.blob_exists( PrevMHISACBlobPath ) ) )
    ):

        # all SCH & STH models have same nYears & outputFrequency
        nYears = 12
        outputFrequency = 6

        # we're about to kick off a new simulation
        Result[ 'isNewSimulation' ] = True

        STH_Simulation(
            paramFileName = paramFileName, # comes from inside the python module
            demogName = "WHOGeneric", # standard for STH
            MDAFilePath = GcsMDAFilePath,
            PrevKKSACFilePath = GcsPrevKKSACFilePath,
            PrevMHISACFilePath = GcsPrevMHISACFilePath,
            RkFilePath = GcsRkFilePath,
            nYears = nYears,
            outputFrequency = outputFrequency, # restrict the number of columns in the CSV output
            numReps = numReps,
            SaveOutput = False,
            OutSimFilePath = None,
            InSimFilePath = InSimFilePath,
            useCloudStorage = True,
            cloudModule = gcs,
            logger = app.logger
        )

        # summarize generated future KKSAC prevalence data (predictions)
        generate_summary( GcsPrevKKSACFilePath, GcsPrevKKSACSummaryFilePath )

        # summarize historical KKSAC prevalence data
        generate_summary( GcsHistoricalKKSACPrevFilePath, GcsHistoricalKKSACPrevSummaryFilePath )

        # summarize generated future MHISAC prevalence data (predictions)
        generate_summary( GcsPrevMHISACFilePath, GcsPrevMHISACSummaryFilePath )

        # summarize historical MHISAC prevalence data
        generate_summary( GcsHistoricalMHISACPrevFilePath, GcsHistoricalMHISACPrevSummaryFilePath )

    ############################################################################

    try:

        # snag the output for sending to browser now
        output_result_json = json.dumps( Result )

        # save result to file for JS to hit next time
        ResultJsonFilePath = f"{OutputDirectoryPath}/{file_abbrev}-{iu}-{request_hash}-info.json"
        Result[ 'isNewSimulation' ] = False # because reading from static file means it's not new
        gcs.write_string_to_file( json.dumps( Result ), ResultJsonFilePath )

        return Response( output_result_json, mimetype = 'application/json; charset=UTF-8' )

    except Exception as e:

        return json.dumps( {
            'status': False,
            'msg': str( e )
        } )


######################
###### TRACHOMA ######
######################
def run_trachoma( request_hash, params ):

    print_function = app.logger.info if app.logger is not None else print

    disease = 'trachoma'
    file_abbrev = file_name_disease_abbreviations[ disease ]

    try:

        # fill in params from UI input
        iu = params[ 'iu' ]
        country = iu[ 0:3 ]
        iu_id = iu[ 3: ]
        numReps = 200 if params[ 'runs' ] > 200 else params[ 'runs' ]
        MDA_Cov = params[ 'coverage' ]
        mda_list = params[ 'mdaRounds' ]

        print_function( f"running Trachoma simulation for {iu} {country} {iu_id} {numReps} {mda_list}" )

        # source directory info
        source_data_path_root = f"diseases/{disease}/source-data"
        source_data_gcs_path_root = f"/{bucket_name}/{source_data_path_root}"

        source_directory_path = f"{source_data_path_root}/{country}/{iu}"
        source_directory_gs_path = f"/{bucket_name}/{source_directory_path}"

        # output directory info
        output_data_path_root = f"diseases/{disease}/output-data"
        output_data_gcs_path_root = f"/{bucket_name}/{output_data_path_root}"

        output_directory_path = f"{output_data_path_root}/{country}/{iu}/{request_hash}"
        output_directory_gs_path = f"/{bucket_name}/{output_directory_path}"

        # generate Input MDA file from input
        mda_file_name = f"InputMDA-{request_hash}.csv"
        mda_file_gcs_path = f"{gs_prefix}{output_directory_gs_path}/{mda_file_name}"

        # Input MDA data
        df = pandas.DataFrame.from_records( [ {
            'start_sim_year': 2020,
            'end_sim_year': 2030,
            'first_mda': '',
            'last_mda': '',
            'mda_vector': json.dumps( mda_list )
        } ] )

        # write Input MDA to file
        df.to_csv( mda_file_gcs_path, index=None )

        # set up GCS & file paths for simulation
        bet_file_gcs_path = f"{gs_prefix}{source_directory_gs_path}/InputBet_{country}{iu_id}.csv"
        infect_file_gcs_path = f"{gs_prefix}{output_directory_gs_path}/InfectFile-{request_hash}.csv"
        in_sim_file_path = f"{source_directory_path}/OutputVals_{country}{iu_id}.p"

        output_prevalence_file_name = f"OutputPrev-{request_hash}.csv"
        output_prevalence_blob_path = f"{output_directory_gs_path}/{output_prevalence_file_name}"
        output_prevalence_gcs_path = f"{gs_prefix}{output_directory_gs_path}/{output_prevalence_file_name}"
        output_prevalence_https_path = f"{https_prefix}{output_directory_gs_path}/{output_prevalence_file_name}"

        # make a json file path to summarise it into
        summary_json_file_name = f"OutputPrev-{request_hash}-summary.json"
        summary_json_gcs_path = f"{output_directory_path}/{summary_json_file_name}"
        summary_json_https_path = f"{https_prefix}{output_directory_gs_path}/{summary_json_file_name}"

        # put together historical prevalence file paths
        historical_prevalence_filename = f"OutputPrev_{country}{iu_id}.csv"
        historical_prevalence_gcs_path = f"{gs_prefix}{source_directory_gs_path}/{historical_prevalence_filename}"
        historical_prevalence_https_path = f"{https_prefix}{source_directory_gs_path}/{historical_prevalence_filename}"

        # check for existing historical prevalence summary
        historical_prevalence_summary_filename = f"OutputPrev_{country}{iu_id}-summary.json"
        historical_prevalence_summary_blob_path = f"{source_directory_gs_path}/{historical_prevalence_summary_filename}"
        historical_prevalence_summary_gcs_path = f"{source_directory_path}/{historical_prevalence_summary_filename}"
        historical_prevalence_summary_https_path = f"{https_prefix}{source_directory_gs_path}/{historical_prevalence_summary_filename}"

        # stick it all in a dict to save to storage and send to client on success
        Result = {
            'status': True,
            'isNewSimulation': False,
            'historicalDataUrl': historical_prevalence_https_path,
            'historicalSummaryUrl': historical_prevalence_summary_https_path,
            'futureDataUrl': output_prevalence_https_path,
            'futureSummaryUrl': summary_json_https_path,
        }

        if not gcs.blob_exists( output_prevalence_blob_path ):

            # we're about to kick off a new simulation
            Result[ 'isNewSimulation' ] = True

            # run the simulation
            Trachoma_Simulation(
                BetFilePath=bet_file_gcs_path,
                MDAFilePath=mda_file_gcs_path,
                PrevFilePath=output_prevalence_gcs_path,
                InfectFilePath=infect_file_gcs_path,
                InSimFilePath=in_sim_file_path,
                SaveOutput=False,
                OutSimFilePath=None,
                MDA_Cov=MDA_Cov,
                numReps = numReps,
                useCloudStorage=True,
                logger = app.logger,
                download_blob_to_file = gcs.download_blob_to_file,
            )

            generate_summary( output_prevalence_gcs_path, summary_json_gcs_path )

            # generate & write one out if it doesn't exist
            if not gcs.blob_exists( historical_prevalence_summary_blob_path ):
                generate_summary( historical_prevalence_gcs_path, historical_prevalence_summary_gcs_path )

        # snag the output for sending to browser now
        output_result_json = json.dumps( Result )

        # save result to file for JS to hit next time
        ResultJsonFilePath = f"{output_directory_path}/{file_abbrev}-{iu}-{request_hash}-info.json"
        Result[ 'isNewSimulation' ] = False # because reading from static file means it's not new
        gcs.write_string_to_file( json.dumps( Result ), ResultJsonFilePath )

        return Response( output_result_json, mimetype = 'application/json; charset=UTF-8' )

    except Exception as e:

        return json.dumps( {
            'status': False,
            'msg': str( e )
        } )

##############################
###### MAIN ENTRY POINT ######
##############################

if __name__ == '__main__':
    app.run( debug = False, host = '0.0.0.0' )
