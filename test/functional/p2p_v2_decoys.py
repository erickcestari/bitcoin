#!/usr/bin/env python3
# Copyright (c) 2024-present The Bitcoin Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
Test BIP324 decoy packet functionality.

Verifies that nodes with decoy packets enabled can:
1. Establish v2 connections with other decoy-enabled nodes
2. Establish v2 connections with nodes without decoys
3. Sync blocks correctly
4. Relay transactions correctly
5. Validate configuration parameters
6. Send additional traffic when decoys are enabled

The timer-based decoy system sends random decoy packets to V2 peers at
configurable intervals for traffic analysis resistance.
"""
import time

from test_framework.test_framework import BitcoinTestFramework
from test_framework.util import assert_equal, assert_greater_than
from test_framework.wallet import MiniWallet


class P2PV2DecoysTest(BitcoinTestFramework):
    def set_test_params(self):
        self.setup_clean_chain = True
        self.num_nodes = 4
        # Timer-based decoy configuration:
        # -v2decoyinterval: how often to check for sending decoys (ms)
        # -v2decoyrate: probability per interval per peer (per mille, e.g., 100 = 10%)
        self.extra_args = [
            # Node 0: decoys enabled with aggressive settings for testing
            ["-v2transport=1", "-v2decoys=1", "-v2decoymaxsize=128", "-v2decoyinterval=10", "-v2decoyrate=500"],
            # Node 1: decoys enabled with defaults
            ["-v2transport=1", "-v2decoys=1"],
            # Node 2: decoys disabled (v2 transport only)
            ["-v2transport=1"],
            # Node 3: default configuration (decoys disabled by default)
            ["-v2transport=1"],
        ]

    def setup_network(self):
        self.setup_nodes()

    def run_test(self):
        self.test_basic_connectivity()
        self.test_decoy_traffic()
        self.test_default_configuration()
        self.test_configuration_validation()
        self.test_node_restart()

    def test_basic_connectivity(self):
        """Test basic v2 connectivity with decoys enabled/disabled."""
        self.log.info("Test v2 connection between decoy-enabled nodes")
        self.connect_nodes(0, 1, peer_advertises_v2=True)
        self._assert_v2_connection(0, 1)

        self.log.info("Test block sync between decoy-enabled nodes")
        self.generate(self.nodes[0], 5, sync_fun=lambda: self.sync_all(self.nodes[0:2]))
        self._assert_chain_synced(self.nodes[0:2], expected_height=5)

        self.log.info("Test v2 connection between decoy-enabled and decoy-disabled nodes")
        self.connect_nodes(1, 2, peer_advertises_v2=True)
        self._assert_v2_connection(1, 2)

        self.log.info("Test block sync across all nodes (mixed decoy configuration)")
        self.connect_nodes(2, 3, peer_advertises_v2=True)
        self.generate(self.nodes[0], 5, sync_fun=self.sync_all)
        self._assert_chain_synced(self.nodes, expected_height=10)

        self.log.info("Test transaction relay with decoys enabled")
        wallet = MiniWallet(self.nodes[0])
        self.generate(wallet, 101, sync_fun=self.sync_all)

        tx = wallet.send_self_transfer(from_node=self.nodes[0])
        self.sync_mempools()
        for node in self.nodes:
            assert tx["txid"] in node.getrawmempool()

        self.log.info("Test block confirmation of relayed transaction")
        self.generate(self.nodes[2], 1, sync_fun=self.sync_all)
        for node in self.nodes:
            assert tx["txid"] not in node.getrawmempool()

    def test_decoy_traffic(self):
        """Test that decoy-enabled nodes send traffic while idle."""
        self.log.info("Test that decoys generate traffic on an otherwise idle node")

        # Ensure network is quiet
        self.sync_all()
        time.sleep(0.2)

        bytes_before = self._get_total_bytes_sent(0) # aggressive decoy config

        # Observe over several intervals
        for _ in range(5):
            time.sleep(0.2)
            bytes_now = self._get_total_bytes_sent(0)
            if bytes_now > bytes_before:
                break
        else:
            assert False, "Expected decoy traffic, but bytessent did not increase"

        self.log.info(f"Decoy traffic observed: {bytes_now - bytes_before} bytes")


    def test_default_configuration(self):
        """Test that default configuration (decoys disabled) works correctly."""
        self.log.info("Test default configuration path (decoys disabled)")

        # Node 3 uses default configuration, verify it can sync and relay
        self._assert_v2_connection(2, 3)
        current_height = self.nodes[0].getblockcount()
        self._assert_chain_synced(self.nodes, expected_height=current_height)

    def test_configuration_validation(self):
        """Test that invalid configuration values are rejected."""
        self.log.info("Test configuration validation")

        # Test invalid v2decoymaxsize (too small)
        self.log.info("Testing invalid -v2decoymaxsize (too small)")
        self.stop_node(3)
        self.nodes[3].assert_start_raises_init_error(
            extra_args=["-v2transport=1", "-v2decoys=1", "-v2decoymaxsize=0"],
            expected_msg="Error: -v2decoymaxsize must be between 1 and 4096 bytes"
        )

        # Test invalid v2decoymaxsize (too large)
        self.log.info("Testing invalid -v2decoymaxsize (too large)")
        self.nodes[3].assert_start_raises_init_error(
            extra_args=["-v2transport=1", "-v2decoys=1", "-v2decoymaxsize=10000"],
            expected_msg="Error: -v2decoymaxsize must be between 1 and 4096 bytes"
        )

        # Test invalid v2decoyinterval (too small)
        self.log.info("Testing invalid -v2decoyinterval (too small)")
        self.nodes[3].assert_start_raises_init_error(
            extra_args=["-v2transport=1", "-v2decoys=1", "-v2decoyinterval=5"],
            expected_msg="Error: -v2decoyinterval must be between 10 and 60000 milliseconds"
        )

        # Test invalid v2decoyinterval (too large)
        self.log.info("Testing invalid -v2decoyinterval (too large)")
        self.nodes[3].assert_start_raises_init_error(
            extra_args=["-v2transport=1", "-v2decoys=1", "-v2decoyinterval=100000"],
            expected_msg="Error: -v2decoyinterval must be between 10 and 60000 milliseconds"
        )

        # Test invalid v2decoyrate (negative)
        self.log.info("Testing invalid -v2decoyrate (negative)")
        self.nodes[3].assert_start_raises_init_error(
            extra_args=["-v2transport=1", "-v2decoys=1", "-v2decoyrate=-1"],
            expected_msg="Error: -v2decoyrate must be between 0 and 1000 (per mille)"
        )

        # Test invalid v2decoyrate (too large)
        self.log.info("Testing invalid -v2decoyrate (too large)")
        self.nodes[3].assert_start_raises_init_error(
            extra_args=["-v2transport=1", "-v2decoys=1", "-v2decoyrate=1001"],
            expected_msg="Error: -v2decoyrate must be between 0 and 1000 (per mille)"
        )

        # Restart node 3 with valid configuration for remaining tests
        self.start_node(3)
        self.connect_nodes(2, 3, peer_advertises_v2=True)

    def test_node_restart(self):
        """Test node restart with different decoy configurations."""
        self.log.info("Test node restart with different decoy configuration")

        self.restart_node(0, extra_args=[
            "-v2transport=1", "-v2decoys=1",
            "-v2decoymaxsize=256", "-v2decoyinterval=200", "-v2decoyrate=50"
        ])
        self.connect_nodes(0, 1, peer_advertises_v2=True)
        self.generate(self.nodes[0], 5, sync_fun=self.sync_all)

        current_height = self.nodes[0].getblockcount()
        self._assert_chain_synced(self.nodes, expected_height=current_height)

    def _assert_v2_connection(self, node_a_idx, node_b_idx):
        """Verify that a v2 transport connection exists between two nodes."""
        for idx in (node_a_idx, node_b_idx):
            peer_info = self.nodes[idx].getpeerinfo()
            assert any(p["transport_protocol_type"] == "v2" for p in peer_info), \
                f"Node {idx} has no v2 connections"

    def _assert_chain_synced(self, nodes, expected_height):
        """Verify all nodes are at the expected height with matching tip."""
        tip = nodes[0].getbestblockhash()
        for node in nodes:
            assert_equal(node.getblockcount(), expected_height)
            assert_equal(node.getbestblockhash(), tip)

    def _get_total_bytes_sent(self, node_idx):
        """Get the total bytes sent by a node to all peers."""
        peer_info = self.nodes[node_idx].getpeerinfo()
        return sum(p.get("bytessent", 0) for p in peer_info)


if __name__ == '__main__':
    P2PV2DecoysTest(__file__).main()
