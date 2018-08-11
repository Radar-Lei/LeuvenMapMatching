#!/usr/bin/env python3
# encoding: utf-8
"""
tests.test_path_newsonkrumm2009
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Based on the data available at:
https://www.microsoft.com/en-us/research/publication/hidden-markov-map-matching-noise-sparseness/

:author: Wannes Meert
:copyright: Copyright 2018 DTAI, KU Leuven and Sirris.
:license: Apache License, Version 2.0, see LICENSE for details.
"""
import os
import sys
import logging
import pickle
from pathlib import Path
import csv
from datetime import datetime
import leuvenmapmatching as mm
from leuvenmapmatching.matching_distance import MatcherDistance
from leuvenmapmatching.map.inmemmap import InMemMap
import leuvenmapmatching.visualization as mm_viz
MYPY = False
if MYPY:
    from typing import List, Tuple


this_path = Path(os.path.realpath(__file__)).parent / "rsrc" / "newson_krumm_2009"
gps_data = this_path / "gps_data.txt"
gps_data_pkl = gps_data.with_suffix(".pkl")
gps_data_xy_pkl = this_path / "gps_data_xy.pkl"
ground_truth_route = this_path / "ground_truth_route.txt"
road_network = this_path / "road_network.txt"
road_network_pkl = road_network.with_suffix(".pkl")
road_network_xy_pkl = this_path / "road_network_xy.pkl"

directory = None


def read_gps(route_fn):
    route = []
    with route_fn.open("r") as route_f:
        reader = csv.reader(route_f, delimiter='\t')
        next(reader)
        for row in reader:
            date, time, lat, lon = row[:4]
            date_str = date + " " + time
            ts = datetime.strptime(date_str, '%d-%b-%Y %H:%M:%S')
            lat = float(lat)
            lon = float(lon)
            route.append((lat, lon, ts))
    mm.matching.logger.debug(f"Read GPS trace of {len(route)} points")
    return route


def read_nodes(nodes_fn):
    nodes = []
    with nodes_fn.open("r") as nodes_f:
        reader = csv.reader(nodes_f, delimiter='\t')
        next(reader)
        for row in reader:
            nodeid, trav = row[:2]
            nodeid = int(nodeid)
            trav = int(trav)
            nodes.append((nodeid, trav))
    mm.matching.logger.debug(f"Read correct trace of {len(nodes)} nodes")
    return nodes


def parse_linestring(line):
    # type: (str) -> List[Tuple[float, float]]
    line = line[line.index("(") + 1:line.index(")")]
    latlons = []
    for lonlat in line.split(", "):
        lon, lat = lonlat.split(" ")
        latlons.append((float(lat), float(lon)))
    return latlons


def read_map(map_fn):
    mmap = InMemMap("road_network", use_latlon=True, use_rtree=False, dir=this_path)
    node_cnt = 0
    edge_cnt = 0
    with map_fn.open("r") as map_f:
        reader = csv.reader(map_f, delimiter='\t')
        next(reader)
        for row in reader:
            eid, nf, nt, twoway, speed, length,  innernodes = row
            nf = int(nf)
            nt = int(nt)
            length = int(length)
            innernodes = parse_linestring(innernodes)
            # Add nodes to map
            mmap.add_node(nf, innernodes[0])
            mmap.add_node(nt, innernodes[-1])
            node_cnt += 2
            prev_node = nf
            assert(length < 1000)
            for idx, innernode in enumerate(innernodes[1:-1]):
                innernode_id = nf * 1000 + idx
                mmap.add_node(innernode_id, innernode)
                node_cnt += 1
                mmap.add_edge(prev_node, innernode_id)
                mmap.add_edge(innernode_id, prev_node)
                edge_cnt += 2
                prev_node = innernode_id
            mmap.add_edge(prev_node, nt)
            mmap.add_edge(nt, prev_node)
    mm.matching.logger.debug(f"Read map with {node_cnt} nodes and {edge_cnt} edges")
    return mmap


def load_data():
    max_route_length = 200

    # Nodes
    nodes = read_nodes(ground_truth_route)
    # Map
    if road_network_pkl.exists() and road_network_xy_pkl.exists():
        map_con_latlon = InMemMap.from_pickle(road_network_pkl)
        mm.matching.logger.debug(f"Read latlon road network from file ({map_con_latlon.size()} nodes)")
        map_con = InMemMap.from_pickle(road_network_xy_pkl)
        mm.matching.logger.debug(f"Read xy road network from file ({map_con.size()} nodes)")
    else:
        map_con_latlon = read_map(road_network)
        map_con_latlon.dump()
        mm.matching.logger.debug(f"Saved latlon road network to file ({map_con_latlon.size()} nodes)")
        map_con = map_con_latlon.to_xy(name="road_network_xy", use_rtree=True)
        map_con.dump()
        mm.matching.logger.debug(f"Saved xy road network to file ({map_con.size()} nodes)")

    # Route
    if gps_data_pkl.exists() and gps_data_xy_pkl.exists():
        with gps_data_pkl.open("rb") as ifile:
            route_latlon = pickle.load(ifile)
        with gps_data_xy_pkl.open("rb") as ifile:
            route = pickle.load(ifile)
    else:
        route_latlon = read_gps(gps_data)
        if max_route_length:
            route_latlon = route_latlon[:max_route_length]
        with gps_data_pkl.open("wb") as ofile:
            pickle.dump(route_latlon, ofile)
        route = [map_con.latlon2yx(lat, lon) for lat, lon, _ in route_latlon]
        with gps_data_xy_pkl.open("wb") as ofile:
            pickle.dump(route, ofile)

    return nodes, map_con, map_con_latlon, route, route_latlon


def test_route():
    nodes, map_con, map_con_latlon, route, route_latlon = load_data()

    if directory is not None:
        mm.matching.logger.debug("Plotting pre map ...")
        mm_viz.plot_map(map_con_latlon, path=route_latlon, use_osm=True,
                        show_lattice=False, show_labels=False, show_graph=False, zoom_path=True,
                        filename=str(directory / "test_newson_route.png"))
        mm.matching.logger.debug("... done")

    matcher = MatcherDistance(map_con, min_prob_norm=0.0001,
                              max_dist=200, obs_noise=4.07, only_edges=True,  # Newson Krumm defaults
                              non_emitting_states=False)
    matcher.match(route)
    path_pred = matcher.path_pred_onlynodes

    if directory:
        matcher.print_lattice_stats()
        mm.matching.logger.debug("Plotting post map ...")
        mm_viz.plot_map(map_con, matcher=matcher, use_osm=True,
                        show_lattice=False, show_labels=False, show_graph=False, zoom_path=True,
                        coord_trans=map_con.yx2latlon,
                        filename=str(directory / "test_newson_route_matched.png"))
        mm.matching.logger.debug("... done")


if __name__ == "__main__":
    mm.matching.logger.setLevel(logging.DEBUG)
    mm.matching.logger.addHandler(logging.StreamHandler(sys.stdout))
    directory = Path(os.environ.get('TESTDIR', Path(__file__).parent))
    print(f"Saving files to {directory}")
    test_route()