# Supplied PA Pattern photographs

The user supplied these ten original JPEGs from one physical batch print job. All images are 4000 × 3000 encoded pixels; EXIF orientation must be applied before interpreting image coordinates. The originals remain in Downloads. The project copies under `fixtures/images/` retain the JPEG image data and orientation but remove other EXIF, XMP, comments, and camera metadata, including GPS data. Decoding and applying orientation to each project copy produced the same pixels and dimensions as its original. No photograph has been sent to a model API.

| Original file | View | EXIF orientation | Original SHA-256 | Project copy SHA-256 |
| --- | --- | ---: | --- | --- |
| [20260924_191535.jpg](/home/dima/Downloads/20260924_191535.jpg) | Nine-pattern overview | 3 | `64084825e7315425fe09591cb089a4c4ec3ce5382be20f4ebe1aa00310baf904` | `0e1b5df56d5b1a162a16ee78dc59be7a47b9b5ddd9a1863e45c18d8c14652191` |
| [20260924_191541.jpg](/home/dima/Downloads/20260924_191541.jpg) | Detail | 6 | `0668ec5a29434177445e0ef7a1876caffcc775b738b306ab36d626d82f365806` | `05e82ad13691b217ff258b6c760fe229b396b01d3f9607bc62758b333c180fc9` |
| [20260924_191544.jpg](/home/dima/Downloads/20260924_191544.jpg) | Detail | 6 | `732da087c25046263833f583b037773f8c9e6fee491f548d8058a02e60c77af0` | `7fc27e63a06da67625c5032b66f01bda660a2c1fa1f11f4a5153429987ca0f27` |
| [20260924_191547.jpg](/home/dima/Downloads/20260924_191547.jpg) | Detail | 6 | `42b290807c8f03f4a8705e15d1c028400bb5d8ea85ba4587e4be79b53a68a39a` | `5efad9a535ab04f05e3912cb9c8ee3429b1e00653163b775900ea8ceb0d2b3c7` |
| [20260924_191551.jpg](/home/dima/Downloads/20260924_191551.jpg) | Detail | 6 | `0b638b3d4efdc19e546e66f7647f68e728a08a302ed955a3c20d1baeabbc6bb4` | `451beb84e3068fda6872340219a0646b40551e06ea67d366910f5442b8565899` |
| [20260924_191553.jpg](/home/dima/Downloads/20260924_191553.jpg) | Detail | 6 | `f097a4ff96c0f5a3be0e621be877857ea3c48c1a2307562529d594b6be933441` | `ab0d58659a23b84150ee88de5a83028c7980dc8beab616210735c8578929d799` |
| [20260924_191556.jpg](/home/dima/Downloads/20260924_191556.jpg) | Detail | 6 | `4efc16e41973f42efa255affc5dc7149a78088d7e0ac27d2f93b7b93c350ae03` | `466f82b66c881d7d1abfff6f391d424021df9bd38da84a776bbd47c5b9579b7c` |
| [20260924_191559.jpg](/home/dima/Downloads/20260924_191559.jpg) | Detail | 6 | `af141acb245a02fc49d8d8f140834c877b0ef90774a51d6fbccf21000bb0dd3a` | `a38f67cf6281099c8d2878ed27b67b08d1b6d68ee11e6a020e799cd7c6a6fba4` |
| [20260924_191602.jpg](/home/dima/Downloads/20260924_191602.jpg) | Detail | 6 | `fc82a1e0dde30d1b7fdf2a117a0db9b8e3ba5687435bc4a314c3d2df0689aa9d` | `0258df0a34a97e34afc17c4adb1edc3fd6845ff994d10f958ee54a0c146ccab9` |
| [20260924_191604.jpg](/home/dima/Downloads/20260924_191604.jpg) | Detail | 6 | `50d2e505e7570e61c03e57dd2c24cf4afd5afbb0b3be64a073e0cb8fe17314fa` | `62ccb02d6437d9914eb80895b148883310991bb11823070ac9f682ceaac2eb84` |

The detail frames show readable herringbone geometry but embossed white-on-white labels, glare, and overlapping neighbouring patterns. Exact pattern identity for each close view remains unverified; do not infer a one-to-one mapping from file order. The full overview contains all nine patterns and must not enter development model inputs until the held-out split is frozen and held-out patterns are excluded or masked. The project copies have the same filenames under `fixtures/images/`; their hashes differ only because metadata was removed or replaced with orientation-only EXIF.
