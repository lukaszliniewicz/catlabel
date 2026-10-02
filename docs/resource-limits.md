# Resource limits

[The shared configuration](../catlabel/data/resource_limits.json) supplies both Python and frontend batch ceilings. Changes must update the schema validation and boundary tests together.

| Resource | Ceiling |
| --- | ---: |
| API request body | 64 MiB |
| Uploaded font, PDF or project export | 16 MiB |
| Encoded image after base64 decoding | 8 MiB |
| Batch records, including a matrix product | 1,000 |
| Copies per record | 100 |
| Labels per job | 500 |
| Cumulative render/image pixels | 50,000,000 |
| Image/canvas dimension | 20,000 px |
| Entries in each canvas item/layout list | 10,000 |

The API body guard checks declared and actual bytes before parsing. Authentication and origin checks run first. Matrix products are counted before expansion; canvas dimensions and pages are checked before opening the renderer. Image headers are checked before conversion allocates full pixels. Driver preflight also checks padding, scaling and split output before connecting. These are ceilings, not promises that every boundary-size job will render within a deadline.

Copies must be positive integers; boolean, string and fractional copy counts are rejected. Invalid image data returns a safe error. A rejected job does not start a printer connection. Temporary images and upload resources are released after success or failure.

Fonts must be valid TrueType/OpenType files with a portable filename. Uploading over an existing font is rejected so a failed installation cannot replace a font used by saved designs. PDFs retain the exact 203 DPI scale and enforce page and pixel limits before bitmap allocation.
