from handover.dxf import read

# millimetres, y up, as an architect would draw it: one wall and a closed room on another layer
DRAWING = "\n".join([
    "0", "SECTION", "2", "ENTITIES",
    "0", "LINE", "8", "WALLS", "10", "1000", "20", "5000", "11", "11000", "21", "5000",
    "0", "LWPOLYLINE", "8", "OFFICE", "70", "1",
    "10", "1000", "20", "1000", "10", "4000", "20", "1000", "10", "4000", "20", "3000",
    "0", "ENDSEC", "0", "EOF",
])


def test_lines_and_closed_polylines_in_metres_with_y_down(tmp_path):
    path = tmp_path / "plan.dxf"
    path.write_text(DRAWING)
    segs = read(path, scale=0.001)
    # the wall is the top edge of the drawing, so y = 0 on the plan
    assert segs[0] == (0.0, 0.0, 10.0, 0.0)
    # the room's three corners and the edge back to the first
    assert len(segs) == 4
    assert segs[-1] == (3.0, 2.0, 0.0, 4.0)


def test_layers_filter(tmp_path):
    path = tmp_path / "plan.dxf"
    path.write_text(DRAWING)
    assert len(read(path, scale=0.001, layers={"WALLS"})) == 1
