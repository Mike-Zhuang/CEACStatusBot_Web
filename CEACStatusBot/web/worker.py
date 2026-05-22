import signal
import time
import uuid

from .case_service import claimNextQueryJob, failTimedOutQueryJobs, migrateEncryptedFields, runQueryJob
from .config import getSettings
from .database import initializeDatabase
from .ircc_portal_service import claimNextIrccQueryJob, failTimedOutIrccQueryJobs, runIrccQueryJob
from .korea_visa_service import (
    claimNextKoreaQueryJob,
    failTimedOutKoreaQueryJobs,
    migrateKoreaEncryptedFields,
    runKoreaQueryJob,
)
from .secrets import getCredentialMasterKey


shouldStop = False


def handleStopSignal(_signum, _frame) -> None:
    global shouldStop
    shouldStop = True


def main() -> None:
    settings = getSettings()
    workerId = f"ceac-worker-{uuid.uuid4()}"
    getCredentialMasterKey()
    initializeDatabase()
    migrateEncryptedFields()
    migrateKoreaEncryptedFields()
    signal.signal(signal.SIGTERM, handleStopSignal)
    signal.signal(signal.SIGINT, handleStopSignal)
    print(f"[worker] started {workerId}")
    while not shouldStop:
        failTimedOutQueryJobs()
        failTimedOutIrccQueryJobs(timeoutSeconds=settings.queryJobTimeoutSeconds)
        failTimedOutKoreaQueryJobs(timeoutSeconds=settings.queryJobTimeoutSeconds)
        job = claimNextQueryJob(workerId)
        irccJob = None if job else claimNextIrccQueryJob(workerId)
        koreaJob = None if job or irccJob else claimNextKoreaQueryJob(workerId)
        if not job and not irccJob and not koreaJob:
            time.sleep(settings.workerPollIntervalSeconds)
            continue
        if job:
            print(f"[worker] running job={job['id']} case={job['caseId']} trigger={job['triggerType']}")
            completed = runQueryJob(job)
            print(f"[worker] completed job={completed['id']} status={completed['status']}")
        elif irccJob:
            print(f"[worker] running ircc_job={irccJob['id']} case={irccJob['caseId']} trigger={irccJob['triggerType']}")
            completed = runIrccQueryJob(irccJob)
            print(f"[worker] completed ircc_job={completed['id']} status={completed['status']}")
        elif koreaJob:
            print(f"[worker] running korea_job={koreaJob['id']} case={koreaJob['caseId']} trigger={koreaJob['triggerType']}")
            completed = runKoreaQueryJob(koreaJob)
            print(f"[worker] completed korea_job={completed['id']} status={completed['status']}")
    print(f"[worker] stopped {workerId}")


if __name__ == "__main__":
    main()
