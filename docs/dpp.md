# Digital Product Passport (Level 4)

At Level 4, the simulator generates EU ESPR-compliant Digital Product Passports for manufactured products.

## ESPR Fields (EU Regulation 2024/1781)

| Field | Example |
|-------|---------|
| espr_uid | `urn:epc:id:sgtin:8712345.12345.123456789` |
| data_carrier | QR code with GS1 Digital Link URL |
| economic_operator | MetalFab BV, EORI NL123456789000 |
| product_classification | PRODCOM 24.10.31, HS 7208 |
| substances_of_concern | Nickel (7440-02-0) 8.0% in stainless |
| durability_score | 85.2 / 100 |
| repairability_score | 62.0 / 100 |
| recyclability_score | 78.5 / 100 |

## CO2 Tracking

Each DPP tracks carbon footprint with site-specific grid carbon intensity:

| Site | Grid Carbon | Renewable |
|------|-------------|-----------|
| Eindhoven (NL) | 380 g/kWh | 33% |
| Roeselare (BE) | 160 g/kWh | 25% |
| Brasov (RO) | 260 g/kWh | 44% |

Breakdown: material embodied carbon + per-operation processing emissions + transport.

## Topics

```
umh/v1/metalfab/{site}/_dpp/
  passports/{dpp_id}/
    metadata              Product info, customer, ESPR UID
    carbon_footprint      Total CO2 + breakdown
    traceability          Operations history
    certifications        Compliance, substances, scores
    summary               Dashboard view
  events/
    dpp_created/{dpp_id}
    operation_completed/{dpp_id}
    dpp_finalized/{dpp_id}
    dpp_shipped/{dpp_id}
```

## Subscribe to Events

```bash
mosquitto_sub -t "umh/v1/metalfab/+/_dpp/events/#" -v
```
