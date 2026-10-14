# Checking the flood map against the Environment Agency's Flood Zones

How accurate is GeoFlow's **Flood risk** workflow? This compares it with the Environment Agency's
[Flood Map for Planning](https://environment.data.gov.uk/dataset/04532375-a198-476e-985e-0579a0a11b47),
the official flood zones for England, at two very different places:

- **York:** flat lowland (about 23 m between its lowest and highest ground), where the River Ouse collects
  its water far outside the area.
- **Sheffield:** hilly (about 400 m from low to high), with steep valleys along the Don, Sheaf, Rivelin and
  Loxley.

## Method

[`geoflow-backend/validation/ea_flood_zones.py`](geoflow-backend/validation/ea_flood_zones.py) runs the app's
own node code, connected exactly like the Flood risk template. It downloads the Environment Agency's Flood
Zones 2 and 3 (rivers and sea) through their OGC API, puts them on the same 30 m grid as GeoFlow's result, and
measures how well the two agree inside each place's outline.

- **Flood Zone 3:** land with a 1% or greater chance of flooding from rivers each year (0.5% from the sea).
- **Flood Zone 2:** land with a 0.1% to 1% chance each year.
- **ROC AUC:** the main score. It's the chance that a random spot in a flood zone gets a higher score than a
  random dry spot, so it doesn't depend on where the class breaks are. 0.5 is no better than guessing and 1.0
  is perfect.

Three other methods are scored the same way, to put the result in context:

| Method | What it is |
|---|---|
| GeoFlow (current) | The Flood risk template as it is now |
| Before mapped rivers | The same workflow before rivers from OpenStreetMap were added to the HAND step |
| HAND only | Height above river on its own, without slope or water history |
| Ground height only | A simple rule: the lower the ground, the higher the risk |

To run it yourself (from `geoflow-backend/`):

```bash
.venv/Scripts/python.exe -m validation.ea_flood_zones --place York --match "York and North Yorkshire"
.venv/Scripts/python.exe -m validation.ea_flood_zones --place Sheffield --match "South Yorkshire"
```

## Results

**ROC AUC against Flood Zone 3:**

| Method | York (flat) | Sheffield (hilly) |
|---|---|---|
| **GeoFlow (current)** | **0.77** | **0.92** |
| Before mapped rivers | 0.62 | 0.92 |
| HAND only | 0.80 | 0.93 |
| Ground height only | 0.80 | 0.71 |

**How the classes line up with Flood Zone 3:**

| | York | Sheffield |
|---|---|---|
| Flood Zone 3, share of the area | 9.1% | 3.0% |
| GeoFlow **High**, share of the area | 5.7% | 2.3% |
| Share of High that is in Flood Zone 3 | 47% (5 times the background rate) | 52% (17 times the background rate) |
| Share of High that is in Flood Zone 2 or 3 | 54% | 75% |
| Share of Flood Zone 3 classed Moderate or High | 84% | 82% |
| GeoFlow **Moderate**, share of the area | 44% | 7% |

| York | Sheffield |
|---|---|
| ![Agreement map for York](docs/validation/york-agreement.png) | ![Agreement map for Sheffield](docs/validation/sheffield-agreement.png) |
| ![ROC curves for York](docs/validation/york-roc.png) | ![ROC curves for Sheffield](docs/validation/sheffield-roc.png) |

## What this shows

1. **Strong agreement in hilly places.** In Sheffield, GeoFlow ranks flood zone land with an AUC of 0.92.
   Three quarters of its High class is in Flood Zones 2 or 3, which together cover just 5.5% of the city.
2. **Adding mapped rivers fixed York.** York's AUC rose from 0.62 to 0.77, with no loss in Sheffield.
   Without mapped rivers the River Ouse isn't found, and 44% of York is classed High, of which only 12% is
   in Flood Zone 3.
3. **Height above river beats the simple rule where it matters.** Ground height alone does well in York,
   because York's floodplain is the bottom of one flat basin. It fails in Sheffield (0.71), where valley
   floors sit at very different heights. Height above river works in both places.
4. **Slope and water history add little.** Height above river on its own scores slightly higher than the
   full workflow at both sites (0.80 against 0.77, and 0.93 against 0.92). Giving it more weight is worth
   testing, ideally on more places so the weights aren't tuned to just these two.
5. **The Moderate class is too broad on flat land.** In York it covers 44% of the area, much of it farmland
   outside any flood zone (yellow on the map). Class breaks that change with how hilly the land is would help.

## Limitations

- **Flood Zones aren't the real answer either.** They come from hydraulic modelling, ignore flood defences
  and show particular flood probabilities. GeoFlow's terrain score measures something related but different.
- **Detail.** The Copernicus 30 m elevation model includes buildings and trees, and anything narrower than
  30 m, like small channels and embankments, is lost. Many of the missed areas (red on the maps) are small
  streams and washlands behind walls.
- **Scope.** The Flood Zones only cover flooding from rivers and the sea, not surface water. The results
  come from two places in England, so they give an indication rather than a general answer.

Flood Zones data © Environment Agency, published under the Open Government Licence. Check the
[dataset page](https://environment.data.gov.uk/dataset/04532375-a198-476e-985e-0579a0a11b47) for current terms.
