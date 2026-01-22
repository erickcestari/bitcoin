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
"""
from test_framework.test_framework import BitcoinTestFramework
from test_framework.util import assert_equal
from test_framework.wallet import MiniWallet


class P2PV2DecoysTest(BitcoinTestFramework):
    def set_test_params(self):
        self.setup_clean_chain = True
        self.num_nodes = 3
        self.extra_args = [
            ["-v2transport=1", "-v2decoys=1", "-v2decoymaxsize=128"],  # decoys enabled
            ["-v2transport=1", "-v2decoys=1"],                         # decoys enabled
            ["-v2transport=1"],                                        # decoys disabled
        ]

    def setup_network(self):
        self.setup_nodes()

    def run_test(self):
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

        self.log.info("Test node restart with different decoy configuration")
        self.restart_node(0, extra_args=["-v2transport=1", "-v2decoys=1", "-v2decoymaxsize=256"])
        self.connect_nodes(0, 1, peer_advertises_v2=True)
        self.generate(self.nodes[0], 5, sync_fun=self.sync_all)
        self._assert_chain_synced(self.nodes, expected_height=117)

    def _assert_v2_connection(self, node_a_idx, node_b_idx):
        """Verify that a v2 transport connection exists between two nodes."""
        for idx in (node_a_idx, node_b_idx):
            peer_info = self.nodes[idx].getpeerinfo()
            assert any(p["transport_protocol_type"] == "v2" for p in peer_info), \
                f"Node {idx} has no v2 connections"

    def _assert_chain_synced(self, nodes, expected_height):
        """Verify all nodes are at the expected height with matching tip."""
        tip = nodes[0].getbestblockhash()
        for i, node in enumerate(nodes):
            assert_equal(node.getblockcount(), expected_height)
            assert_equal(node.getbestblockhash(), tip)


if __name__ == '__main__':
    P2PV2DecoysTest(__file__).main()
