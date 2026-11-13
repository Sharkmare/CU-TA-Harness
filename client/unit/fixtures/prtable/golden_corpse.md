**CORPSE  game 1.0.1  25 bare swings, median 0.23 s, corpse 2.5 u, bodies held**

builds: PR24 `0cc68612`, PR24+fix `3d910c4e`, plain `eb318d82`, fix `53f280bb`

### Main tests

| host/client | build | host hp | client hp (min) | broke |
|---|---|---|---|---|
| Milky/Dune | PR24 | 250 | -366.7 | never |
| Milky/Dune | PR24+fix | 3.2-\>gone | -21.4-\>gone | sw11 |
| Dune/Dune | PR24 | 3.2-\>gone | 3.2-\>gone | sw11 |
| Dune/Dune | PR24+fix | 3.2-\>gone | 3.2-\>gone | sw11 |
| Milky/Milky | PR24 | 250 | 250 | never |
| Milky/Milky | PR24+fix | 250 | 250 | never |
| Dune/Milky | PR24 | - | - | - |
| Dune/Milky | PR24+fix | 250 | 250 | never |

Verdict: all 7 valid runs as expected, 1 excluded

### Regression tests

| test | plain | fix |
|---|---|---|
| PvP punches | 1/1 | 3/3 |
| crate swings | 1/1 | 2/3 |
| static copy | 0/1 | 1/4 |
| mining persisted | 1/1 | 2/2 |

Verdict: all 11 valid runs as expected, 5 invalid

### Deviations

- Milky/Dune PR24: 1 excluded (slow swings 0.42 s)
- crate swings fix: 1 invalid (position preflight failed)
- static copy plain: 1 invalid (swing missed, limb lag)
- static copy fix: 3 invalid (swing missed, limb lag x2, client out of band)
