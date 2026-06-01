def job_label(job) -> str:
    if job is None:
        return "Unknown job"
    address = getattr(job, "address", None)
    if address and str(address).strip():
        return str(address).strip()
    customer = getattr(job, "customer_name", None)
    if customer and str(customer).strip():
        return str(customer).strip()
    return "Unknown job"
