def job_label(job) -> str:
    if job is None:
        return "Unknown job"
    customer = getattr(job, "customer_name", None)
    if customer and str(customer).strip():
        label = str(customer).strip()
    else:
        address = getattr(job, "address", None)
        if address and str(address).strip():
            label = str(address).strip()
        else:
            label = "Unknown job"
    if getattr(job, "is_cash", False):
        return f"{label} (Cash)"
    return label
