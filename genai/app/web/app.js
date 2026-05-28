const form = document.getElementById("enrichment-form");
const submitButton = document.getElementById("submit-button");
const statusBanner = document.getElementById("status-banner");
const responseOutput = document.getElementById("response-output");
const analysisStatus = document.getElementById("analysis-status");
const analysisOutcome = document.getElementById("analysis-outcome");
const summaryCount = document.getElementById("summary-count");
const errorCount = document.getElementById("error-count");
const jobId = document.getElementById("job-id");

function normalizeTickers(value) {
    return value
        .split(",")
        .map((ticker) => ticker.trim())
        .filter(Boolean);
}

function buildPayload(formData) {
    const payload = {
        news_id: formData.get("news_id"),
        title: formData.get("title"),
        link: formData.get("link"),
    };

    const tickers = normalizeTickers(formData.get("ticker") || "");
    const source = (formData.get("source") || "").trim();
    const publishedAt = formData.get("published_at");

    if (tickers.length > 0) {
        payload.ticker = tickers;
    }

    if (source) {
        payload.source = source;
    }

    if (publishedAt) {
        payload.published_at = new Date(publishedAt).toISOString();
    }

    return payload;
}

function setLoadingState(isLoading) {
    submitButton.disabled = isLoading;
    submitButton.textContent = isLoading ? "Running..." : "Run Enrichment";
}

function renderResponse(data) {
    analysisStatus.textContent = data.analysis_status || data.status || "unknown";
    analysisOutcome.textContent = data.analysis_outcome || data.outcome || "unknown";
    summaryCount.textContent = String((data.summary_3lines || []).length);
    errorCount.textContent = String((data.errors || []).length);
    jobId.textContent = "n/a";
    responseOutput.textContent = JSON.stringify(data, null, 2);
}

function renderError(message, details) {
    analysisStatus.textContent = "request_failed";
    analysisOutcome.textContent = "fatal_failure";
    summaryCount.textContent = "0";
    errorCount.textContent = "1";
    jobId.textContent = "n/a";
    responseOutput.textContent = JSON.stringify(
        {
            message,
            details,
        },
        null,
        2,
    );
}

function renderAccepted(data) {
    analysisStatus.textContent = data.job?.status || "queued";
    analysisOutcome.textContent = "submitted";
    summaryCount.textContent = "0";
    errorCount.textContent = "0";
    jobId.textContent = data.job?.job_id || "n/a";
    responseOutput.textContent = JSON.stringify(data, null, 2);
}

async function pollResult(newsIdValue) {
    const deadline = Date.now() + 60000;

    while (Date.now() < deadline) {
        const response = await fetch(`/api/v1/news/${encodeURIComponent(newsIdValue)}/result`);
        const data = await response.json();

        if (!response.ok) {
            throw new Error(JSON.stringify(data));
        }

        if (data.result) {
            statusBanner.textContent = "Enrichment completed. Inspect the final payload below.";
            renderResponse(data.result);
            return;
        }

        if (data.latest_job?.status === "failed") {
            statusBanner.textContent = "Enrichment job failed. Inspect the job payload below.";
            analysisStatus.textContent = data.latest_job.status;
            analysisOutcome.textContent = data.latest_job.last_analysis_status || "failed";
            summaryCount.textContent = "0";
            errorCount.textContent = data.latest_job.last_error ? "1" : "0";
            jobId.textContent = data.latest_job.job_id || "n/a";
            responseOutput.textContent = JSON.stringify(data, null, 2);
            return;
        }

        await new Promise((resolve) => setTimeout(resolve, 1000));
    }

    statusBanner.textContent = "Job was submitted, but the final result did not arrive within 60 seconds.";
}

form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(form);
    const payload = buildPayload(formData);

    setLoadingState(true);
    statusBanner.textContent = "Submitting /api/v1/articles/enrich job ...";

    try {
        const response = await fetch("/api/v1/articles/enrich", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify(payload),
        });

        const data = await response.json();

        if (!response.ok) {
            statusBanner.textContent = "Request failed. Inspect the response payload below.";
            renderError("API request failed", data);
            return;
        }

        statusBanner.textContent = "Job accepted. Waiting for the worker to finish processing...";
        renderAccepted(data);
        await pollResult(payload.news_id);
    } catch (error) {
        statusBanner.textContent = "The request could not reach the backend.";
        renderError("Network or server error", String(error));
    } finally {
        setLoadingState(false);
    }
});