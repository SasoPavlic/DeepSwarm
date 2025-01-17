# Copyright (c) 2019 Edvinas Byla
# Licensed under MIT License

import math
import random

from tensorflow.python.keras.models import Model

from . import cfg, left_cost_is_better, data_config
from .dataset import build_validation_dataset
from .log import Log
from .nodes import Node, NeighbourNode
from vizualization import painter
from deepswarm import anomalies


class ACO:
    """Class responsible for performing Ant Colony Optimization."""

    def __init__(self, backend, storage):
        self.graph = Graph()
        self.current_depth = 0
        self.backend = backend
        self.storage = storage

    def search(self):
        """Performs neural architecture search using Ant colony optimization.

        Returns:
            ant which found the best network topology.
        """

        # Generate random ant only if the search started from zero
        if not self.storage.loaded_from_save:
            Log.header("STARTING ACO SEARCH", type="GREEN")
            # Generate Autoencoder graph
            self.best_ant = Ant(self.graph.generate_autoencoder_path(self.random_select))
            self.best_ant.evaluate(self.backend, self.storage)
            Log.info(self.best_ant)
        else:
            Log.header("RESUMING ACO SEARCH", type="GREEN")

        while self.graph.current_depth <= cfg['max_depth']:
            Log.header("Current search depth is %i" % self.graph.current_depth, type="GREEN")
            ants = self.generate_ants()

            # Sort ants using user selected metric
            ants.sort() if cfg['metrics'] == 'loss' else ants.sort(reverse=True)

            # Update the best ant if new better ant is found
            if left_cost_is_better(ants[0].cost, self.best_ant.cost):
                self.best_ant = ants[0]
                Log.header("NEW BEST ANT FOUND", type="GREEN")

            # Log best ant information
            Log.header("BEST ANT DURING ITERATION")
            Log.info(self.best_ant)

            # Perform global pheromone update
            self.update_pheromone(ant=self.best_ant, update_rule=self.global_update)

            # Print pheromone information and increase the graph's depth
            self.graph.show_pheromone()
            self.graph.increase_depth()

            # Perform a backup
            self.storage.perform_backup()
        return self.best_ant

    def generate_ants(self):
        """Generates a new ant population.

        Returns:
            list containing different evaluated ants.
        """

        ants = []
        for ant_number in range(cfg['aco']['ant_count']):
            Log.header("GENERATING ANT %i" % (ant_number + 1))
            ant = Ant(self.graph.generate_autoencoder_path(self.aco_select))
            # Evaluate how good is the new path
            ant.evaluate(self.backend, self.storage)
            ants.append(ant)
            Log.info(ant)
            # Perform local pheromone update
            self.update_pheromone(ant=ant, update_rule=self.local_update)
        return ants

    def random_select(self, neighbours):
        """Randomly selects one neighbour node and its attributes.

        Args:
            neighbours [NeighbourNode]: list of neighbour nodes.
        Returns:
            a randomly selected neighbour node.
        """

        current_node = random.choice(neighbours).node
        current_node.select_random_attributes()
        return current_node

    def aco_select(self, neighbours):
        """Selects one neighbour node and its attributes using ACO selection rule.

        Args:
            neighbours [NeighbourNode]: list of neighbour nodes.
        Returns:
            selected neighbour node.
        """

        # Transform a list of NeighbourNode objects to list of tuples
        # (Node, pheromone, heuristic)
        tuple_neighbours = [(n.node, n.pheromone, n.heuristic) for n in neighbours]
        # Select node using ant colony selection rule
        current_node = self.aco_select_rule(tuple_neighbours)
        # Select custom attributes using ant colony selection rule
        current_node.select_custom_attributes(self.aco_select_rule)
        return current_node

    def aco_select_rule(self, neighbours):
        """Selects neigbour using ACO transition rule.

        Args:
            neighbours [(Object, float, float)]: list of tuples, where each tuple
            contains: an object to be selected, object's pheromone value and
            object's heuristic value.
        Returns:
            selected object.
        """

        probabilities = []
        denominator = 0.0

        # Calculate probability for each neighbour
        for (_, pheromone, heuristic) in neighbours:
            probability = pheromone * heuristic
            probabilities.append(probability)
            denominator += probability

        # Try to perform greedy select: exploitation
        random_variable = random.uniform(0, 1)
        if random_variable <= cfg['aco']['greediness']:
            # Find max probability
            max_probability = max(probabilities)
            # Gather the indices of probabilities that are equal to the max probability
            max_indices = [i for i, j in enumerate(probabilities) if j == max_probability]
            # From those max indices select random index
            neighbour_index = random.choice(max_indices)
            return neighbours[neighbour_index][0]

        # Otherwise perform select using roulette wheel: exploration
        probabilities = [x / denominator for x in probabilities]
        probability_sum = sum(probabilities)
        random_treshold = random.uniform(0, probability_sum)
        current_value = 0
        for neighbour_index, probability in enumerate(probabilities):
            current_value += probability
            if current_value > random_treshold:
                return neighbours[neighbour_index][0]

    def update_pheromone(self, ant, update_rule):
        """Updates the pheromone using given update rule.

        Args:
            ant: ant which should perform the pheromone update.
            update_rule: function which takes pheromone value and ant's cost,
            and returns a new pheromone value.
        """

        current_node = self.graph.input_node
        # Skip the input node as it's not connected to any previous node
        for node in ant.path[1:]:
            # Use a node from the path to retrieve its corresponding instance from the graph
            neighbour = next((x for x in current_node.neighbours if x.node.name == node.name), None)

            # If the path was closed using complete_path method, ignore the rest of the path
            if neighbour is None:
                break

            # Update pheromone connecting to a neighbour
            neighbour.pheromone = update_rule(
                old_value=neighbour.pheromone,
                cost=ant.cost
            )

            # Update attribute's pheromone values
            for attribute in neighbour.node.attributes:
                # Find what attribute value was used for node
                attribute_value = getattr(node, attribute.name)
                # Retrieve pheromone for that value
                old_pheromone_value = attribute.dict[attribute_value]
                # Update pheromone
                attribute.dict[attribute_value] = update_rule(
                    old_value=old_pheromone_value,
                    cost=ant.cost
                )

            # Advance the current node
            current_node = neighbour.node

    def local_update(self, old_value, cost):
        """Performs local pheromone update."""

        decay = cfg['aco']['pheromone']['decay']
        pheromone_0 = cfg['aco']['pheromone']['start']
        return (1 - decay) * old_value + (decay * pheromone_0)

    def global_update(self, old_value, cost):
        """Performs global pheromone update."""

        # Calculate solution cost based on metrics
        added_pheromone = (1 / (cost * 10)) if cfg['metrics'] == 'loss' else cost
        evaporation = cfg['aco']['pheromone']['evaporation']
        return (1 - evaporation) * old_value + (evaporation * added_pheromone)

    def __getstate__(self):
        d = dict(self.__dict__)
        del d['backend']
        return d


class Ant:
    """Class responsible for representing the ant."""

    def __init__(self, autoencoder, path=[]):
        self.encoder = autoencoder[0]
        self.decoder = autoencoder[1]
        self.path = path
        self.loss = math.inf
        self.accuracy = 0.0
        self.path_description = None
        self.path_hash = None

    def evaluate(self, backend, storage):
        """Evaluates how good ant's path is.

        Args:
            backend: Backend object.
            storage: Storage object.
        """

        # Extract path information
        self.path_description, path_hashes = storage.hash_path(self.encoder + self.decoder)
        self.path_hash = path_hashes[-1]

        # Disabled since we can't use reuse model the same way as Conv-NN.
        # Check if the model already exists if yes, then just re-use it
        existing_model, existing_model_hash = (
        None, None)  # storage.load_model(backend, path_hashes, self.encoder + self.decoder)
        if existing_model is None:
            # Generate model
            new_model = backend.generate_model((self.encoder, self.decoder))
        else:
            # Re-use model
            new_model = existing_model

        # Train model
        new_model, history = backend.train_model(new_model, storage)
        # Evaluate model
        self.loss, self.accuracy = backend.evaluate_model(new_model)

        # If the new model was created from the older model, record older model progress
        if existing_model_hash is not None:
            storage.record_model_performance(existing_model_hash, self.cost)

        # Save model
        storage.save_model(backend, new_model, path_hashes, self.cost)
        storage.save_partial_model(backend, path_hashes, "encoder_model", backend.get_encoder_model())
        storage.save_partial_model(backend, path_hashes, "decoder_model", backend.get_decoder_model())

        storage.save_model_shape(path_hashes, 'encoder_shape.png', backend.get_encoder_model())
        storage.save_model_shape(path_hashes, 'decoder_shape.png', backend.get_decoder_model())

        # Display and save graphs
        plt_loss = painter.training_loss(history, epochs=cfg['backend']['epochs'])
        storage.save_plot(path_hashes, 'plt_loss.png', plt_loss)
        plt_loss.show()

        plt_acc = painter.training_acc(history, epochs=cfg['backend']['epochs'])
        storage.save_plot(path_hashes, 'plt_acc.png', plt_acc)
        plt_acc.show()

        plt_recunstructed_results = painter.reconstructed_results(new_model, backend.dataset.x_test)
        storage.save_plot(path_hashes, 'plt_recunstructed_results.png', plt_recunstructed_results)
        plt_recunstructed_results.show()

        plt_MAE_loss = painter.MAE_loss(new_model, backend.dataset.x_train)
        storage.save_plot(path_hashes, 'plt_MAE_loss.png', plt_MAE_loss)
        plt_MAE_loss.show()

        plt_encoded_image = painter.encoded_image(new_model, backend.get_encoder_model(), backend.dataset.x_test)
        storage.save_plot(path_hashes, 'plt_encoded_image.png', plt_encoded_image)
        plt_encoded_image.show()

        # Find anomalies in data
        validLabel = data_config["valid_label"]
        anomalyLabel = data_config["anomaly_label"]
        (x_test, y_test) = build_validation_dataset(validLabel, anomalyLabel)
        plt_anomalies = anomalies.find(new_model, backend.dataset.x_test, backend.dataset.y_test,
                                       cfg['anomaly']['quantile'])
        storage.save_plot(path_hashes, 'plt_anomalies.png', plt_anomalies)
        plt_anomalies.show()

        # Find anomalies in data
        autoencoder = new_model
        print(f"=====================================")
        print(f"Finding anomalies in quantile: 0.995")
        plt_anomalies = anomalies.find(autoencoder, x_test, y_test, 0.995, True, validLabel, anomalyLabel)
        storage.save_plot(path_hashes, f'plt_anomalies_0{str(995)}.png', plt_anomalies)
        plt_anomalies.show()

        print(f"=====================================")
        print(f"Finding anomalies in quantile: 0.98")
        plt_anomalies = anomalies.find(autoencoder, x_test, y_test, 0.98, True, validLabel, anomalyLabel)
        storage.save_plot(path_hashes, f'plt_anomalies_0{str(98)}.png', plt_anomalies)
        plt_anomalies.show()

        print(f"=====================================")
        print(f"Finding anomalies in quantile: 0.9")
        plt_anomalies = anomalies.find(autoencoder, x_test, y_test, 0.9, True, validLabel, anomalyLabel)
        storage.save_plot(path_hashes, f'plt_anomalies_0{str(9)}.png', plt_anomalies)
        plt_anomalies.show()

        # Evaluate model
        roc_curve = anomalies.calculate_roc_curve(new_model, x_test, y_test, False, validLabel, anomalyLabel)
        storage.save_plot(path_hashes, 'roc_curve.png', roc_curve)
        roc_curve.show()

    @property
    def cost(self):
        """Returns value which represents ant's cost."""

        return self.loss if cfg['metrics'] == 'loss' else self.accuracy

    def __lt__(self, other):
        return self.cost < other.cost

    def __str__(self):
        return "======= \n Ant: %s \n Loss: %f \n Accuracy: %f \n Path: %s \n Hash: %s \n=======" % (
            hex(id(self)),
            self.loss,
            self.accuracy,
            self.path_description,
            self.path_hash,
        )


class Graph:
    """Class responsible for representing the graph."""

    def __init__(self, current_depth=0):
        self.topology = []
        self.current_depth = cfg['min_depth'] if cfg['min_depth'] < cfg['max_depth'] else 0
        self.input_node = self.get_node(Node.create_using_type('Input'), self.current_depth)
        self.input_decoder_node = self.get_node(Node.create_using_name('InputDecoderNode'), current_depth)
        if self.current_depth == 0:
            self.increase_depth()
        self.latent_dim = 16

    def get_node(self, node, depth):
        """Tries to retrieve a given node from the graph. If the node does not
        exist then the node is inserted into the graph before being retrieved.

        Args:
            node: Node which should be found in the graph.
            depth: depth at which the node should be stored.
        """

        # If we are trying to insert the node into a not existing layer, we pad the
        # topology by adding empty dictionaries, until the required depth is reached
        while depth > (len(self.topology) - 1):
            self.topology.append({})

        # If the node already exists return it, otherwise add it to the topology first
        return self.topology[depth].setdefault(node.name, node)

    def increase_depth(self):
        """Increases the depth of the graph."""

        self.current_depth += 1

    def generate_encoder_path(self, select_rule):
        """Generates encoder path through the graph based on given selection rule.
        Args:
            select_rule ([NeigbourNode]): function which receives a list of
            neighbours.
        Returns:
            a encoder path which contains Node objects.
        """

        current_node = self.input_node
        path = [current_node.create_deepcopy()]
        for depth in range(self.current_depth):
            # If the node doesn't have any neighbours stop expanding the path
            if not self.has_neighbours(current_node, depth):
                break

            # Select node using given rule
            current_node = select_rule(current_node.neighbours)
            # Add only the copy of the node, so that original stays unmodified
            path.append(current_node.create_deepcopy())

        path.append(self.get_node(Node.create_using_type('Flatten'), len(path)))
        latent_space_node = self.get_node(Node.create_using_type('LatentSpace'), len(path))
        self.latent_dim = latent_space_node.output_size
        path.append(latent_space_node)

        return path

    def generate_decoder_path(self, select_rule):
        """Generates decoder path through the graph based on encoder.
        Args:
            select_rule ([NeigbourNode]): function which receives a list of
            neighbours.
        Returns:
            a decoder path which contains Node objects.
        """

        current_node = self.input_decoder_node
        current_node.shape = self.latent_dim
        path = [current_node.create_deepcopy()]
        current_node = self.get_node(Node.create_using_type('Dense'), len(path))
        path.append(current_node)
        current_node = self.get_node(Node.create_using_type('Reshape'), len(path))
        path.append(current_node)

        for depth in range(self.current_depth):
            # If the node doesn't have any neighbours stop expanding the path
            if not self.has_neighbours(current_node, depth):
                break

            # Select node using given rule
            current_node = select_rule(current_node.neighbours)
            # Add only the copy of the node, so that original stays unmodified
            path.append(current_node.create_deepcopy())

        path.append(self.get_node(Node.create_using_type('Output'), len(path)))

        return path

    def generate_autoencoder_path(self, select_rule):
        """Generates encoder and decoder

        Args:
            select_rule ([NeigbourNode]): function which receives a list of
            neighbours.

        Returns:
            encoder and decoder paths
        """

        encoder = self.generate_encoder_path(select_rule)
        decoder = self.generate_decoder_path(select_rule)
        autoencoder = (encoder, decoder)

        return autoencoder

    def generate_path(self, select_rule):
        """Generates path through the graph based on given selection rule.
        Args:
            select_rule ([NeigbourNode]): function which receives a list of
            neighbours.
        Returns:
            a path which contains Node objects.
        """

        current_node = self.input_node
        path = [current_node.create_deepcopy()]
        for depth in range(self.current_depth):
            # If the node doesn't have any neighbours stop expanding the path
            if not self.has_neighbours(current_node, depth):
                break

            # Select node using given rule
            current_node = select_rule(current_node.neighbours)
            # Add only the copy of the node, so that original stays unmodified
            path.append(current_node.create_deepcopy())

        completed_path = self.complete_path(path)
        return completed_path

    def has_neighbours(self, node, depth):
        """Checks if the node has any neighbours.

        Args:
            node: Node that needs to be checked.
            depth: depth at which the node is stored in the graph.

        Returns:
            a boolean value which indicates if the node has any neighbours.
        """

        # Expand only if it hasn't been expanded
        if node.is_expanded is False:
            available_transitions = node.available_transitions
            for (transition_name, heuristic_value) in available_transitions:
                neighbour_node = self.get_node(Node(transition_name), depth + 1)
                node.neighbours.append(NeighbourNode(neighbour_node, heuristic_value))
            node.is_expanded = True

        # Return value indicating if the node has neighbours after being expanded
        return len(node.neighbours) > 0

    def complete_path(self, path):
        """Completes the path if it is not fully completed (i.e. missing OutputNode).
        Args:
            path [Node]: list of nodes defining the path.
        Returns:
            completed path which contains list of nodes.
        """

        # If the path is not completed, then complete it and return completed path
        # We intentionally don't add these ending nodes as neighbours to the last node
        # in the path, because during the first few iterations these nodes will always be part
        # of the best path (as it's impossible to close path automatically when it's so short)
        # this would result in bias pheromone received by these nodes during later iterations
        if path[-1].name in cfg['spatial_nodes']:
            path.append(self.get_node(Node.create_using_type('Flatten'), len(path)))
        if path[-1].name in cfg['flat_nodes']:
            path.append(self.get_node(Node.create_using_type('Output'), len(path)))
        return path

    def show_pheromone(self):
        """Logs the pheromone information for the graph."""

        # If the output is disabled by the user then don't log the pheromone
        if cfg['aco']['pheromone']['verbose'] is False:
            return

        Log.header("PHEROMONE START", type="RED")
        for idx, layer in enumerate(self.topology):
            info = []
            for node in layer.values():
                for neighbour in node.neighbours:
                    info.append("%s [%s] -> %f -> %s [%s]" % (node.name, hex(id(node)),
                                                              neighbour.pheromone, neighbour.node.name,
                                                              hex(id(neighbour.node))))

                    # If neighbour node doesn't have any attributes skip attribute info
                    if not neighbour.node.attributes:
                        continue

                    info.append("\t%s [%s]:" % (neighbour.node.name, hex(id(neighbour.node))))
                    for attribute in neighbour.node.attributes:
                        info.append("\t\t%s: %s" % (attribute.name, attribute.dict))
            if info:
                Log.header("Layer %d" % (idx + 1))
                Log.info('\n'.join(info))
        Log.header("PHEROMONE END", type="RED")
