# Compatible tablets

The driver speaks the protocol of the Linux kernel's `aiptek` driver and accepts every USB ID that driver
supports. On connect it **asks the tablet for its active area**, so models with a different size configure
themselves.

## Tested

| Tablet | USB ID | Status |
|---|---|---|
| Aiptek HyperPen 12000U | `08CA:0010` | ✅ works: position, pressure, side button, coil correction |

## Should work (same protocol, not yet tested)

These USB IDs are in the Linux `aiptek` driver's device table, and the driver accepts them:

| USB ID | Notes |
|---|---|
| `08CA:0001` | Aiptek HyperPen (earlier models, e.g. 4000U/5000U/6000U) |
| `08CA:0020`, `08CA:0021`, `08CA:0022`, `08CA:0023`, `08CA:0024` | Aiptek HyperPen family (e.g. 6000U/8000U variants) |
| `0458:5003` | a Genius (KYE Systems) tablet using the same protocol |

The Linux driver names the line *"Aiptek HyperPen USB Tablets (4000U/5000U/6000U/8000U/12000U)"*, and notes
that these IDs are **not model-specific**: the same model can show up with different IDs, and the same ID
can be used by different models. So look up your tablet's **USB ID** rather than its name:
*Device Manager → (tablet, usually under Human Interface Devices as "USB Input Device") → Properties →
Details → Hardware Ids*.

## Rebrands to try

Aiptek built tablets that were sold under other brands. The aiptektablet project lists these as "similar
enough" to work with the Aiptek driver:

* **Trust Wireless Tablet 400**
* **LIFETEC LT9750**
* **Medion MD9750**

Seller listings also suggest that 12" tablets such as **Trust TB-3100**, **Genius G-Pen F610** and the
**Waltop Q Pad** share hardware with the HyperPen 12000U. That isn't verified, and some of these use a
different chip (Waltop/UC-Logic) and protocol, so they will only work if their USB ID is in the list above.

## Not supported

* Newer Aiptek tablets (e.g. *Slim*, *MediaTablet*, *HyperPen Mini*) and other tablets with
  **UC-Logic/Huion or Waltop** chips use different protocols. Try
  [OpenTabletDriver](https://opentabletdriver.net/), which supports many of them.
* Serial (RS-232) HyperPens.

## Trying an untested model

1. **Before** installing, plug the tablet in and note its USB ID. With Python available,
   `python tools/probe.py` (edit the VID/PID at the bottom of `hidwin.find_aiptek` if needed) and
   `python tools/sniff.py` show whether it answers the mode-switch command and sends absolute reports
   `02 xL xH yL yH status pL pH`.
2. Install the app. The log shows `Tablet XXXX:XXXX connected ... active area (W, H)`.
3. In Settings, check that the pen dot covers the whole tablet, and calibrate pressure.
4. **Coil correction** is only applied on the 12000U (its calibration was measured there). To calibrate
   another model, record ruler strokes with `tools/record.py` and fit them with `tools/fit_calib.py`, then
   put the result in `config.json` → `calibration`.

Please report results (working or not) in an issue, so this list can grow.
