# Privacy and public metadata

Public dataset metadata is limited to release and record identifiers, category,
risk, source classification, licence, review status, revision, timestamps, and
integrity hashes. Certificates and dashboards exclude reviewer identifiers,
notes, ownership/consent evidence, raw legacy evidence paths, absolute local
paths, environment variables, and secrets.

Offline exports strip internal fields and scan recursively for forbidden keys and
secret-like assignments. Source *classification* is public; sensitive underlying
evidence remains in the local review workflow. These controls reduce exposure but
do not replace contributor privacy review.
