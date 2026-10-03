# Print jobs and hardware acceptance

One running process admits one print job per canonical device address. A competing request receives HTTP 409 before scanning or connecting. This is admission control, not a persistent queue or a cross-process lock: run one CatLabel process for a printer.

A successful print request returns `status: submitted`, the `submitted` label count and `physical_completion: unverified`. It confirms the client completed its send operation, not that every physical label emerged. An error includes `stage`, an `error_id` and `delivery_uncertain`. Lost replies, connection failures during transfer and browser timeouts can leave delivery uncertain. Check the physical output before resubmitting; a retry can duplicate labels. CatLabel does not automatically replay uncertain print jobs.

Hardware acceptance currently targets a PD01 cat printer and a Niimbot identified by its owner as D111 or D100. The exact Niimbot model and firmware still need confirmation. Source and fixture tests are recorded separately from physical printing.

Browser preparation has a local job identity. Cancelled, superseded or duplicate
render callbacks cannot submit that job again. Cancelling preparation happens
before submission; it does not stop a physical transfer already running. The editor
shows a validated submission receipt with physical completion explicitly unverified.
