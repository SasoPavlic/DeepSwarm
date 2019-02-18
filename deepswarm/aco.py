# Copyright (c) 2019 Edvinas Byla
# Licensed under MIT License

import hashlib
import random
import math
from . import cfg, comparison_operator
from .graph import Graph
from .log import Log


class ACO:
    def __init__(self, max_depth, ant_count, backend, storage):
        self.graph = Graph()
        self.current_depth = 0
        self.max_depth = max_depth
        self.ant_count = ant_count
        self.backend = backend
        self.greediness = 0.5
        self.storage = storage

    def search(self):
        """ Performs ant colony system optimization over the graph.

        Returns:
            ant which found best network topology
        """

        # Generate random ant only if search started from zero
        if not self.storage.loaded_from_save:
            Log.header("STARTING ACO SEARCH", type="GREEN")
            Log.info("Max depth: %s\t Ant count: %s" % (self.max_depth, self.ant_count))
            self.best_ant = Ant(self.graph.generate_path(self.random_select))
            self.best_ant.evaluate(self.backend, self.storage)
            Log.info(self.best_ant)
        else:
            Log.header("RESUMING ACO SEARCH", type="GREEN")

        while self.graph.current_depth <= self.max_depth:
            ants = self.generate_ants()
            # Sort ants depending on user selected metric
            ants.sort() if cfg['metrics'] == 'loss' else ants.sort(reverse=True)
            # If any of the new solutions has lower cost than best solution, update best
            if comparison_operator(ants[0].cost, self.best_ant.cost):
                self.best_ant = ants[0]
                Log.header("NEW BEST ANT FOUND", type="GREEN")

            Log.header("BEST ANT DURING ITERATION")
            Log.info(self.best_ant)
            # Do global pheromone update
            self.update_pheromone(ant=self.best_ant, update_rule=self.global_update)
            # Print pheromone information and increase graph's depth
            self.graph.show_pheromone()
            self.graph.increase_depth()
            # Do a backup
            self.storage.perform_backup()
        return self.best_ant

    def generate_ants(self):
        ants = []
        for ant_number in range(self.ant_count):
            Log.header("GENERATING ANT %i" % (ant_number + 1))
            ant = Ant()
            # Generate ant's path using given ACO rule
            ant.path = self.graph.generate_path(self.aco_select)
            # TODO: Check if path is unique if not then don't evaluate this ant
            # and use stats from already evaluated ant
            ant.evaluate(self.backend, self.storage)
            ants.append(ant)
            Log.info(ant)
            self.update_pheromone(ant=ant, update_rule=self.local_update)
        return ants

    def random_select(self, neighbours):
        current_node = random.choice(neighbours).node
        current_node.select_random_attributes()
        return current_node

    def aco_select(self, neighbours):
        # Transform List of NeighbourNode objects to tuples (Node, Pheromone)
        tuple_neighbours = [(n.node, n.pheromone) for n in neighbours]
        current_node = self.aco_select_rule(tuple_neighbours)[0]
        current_node.select_custom_attributes(self.aco_select_rule)
        return current_node

    def aco_select_rule(self, neighbours):
        """Selects neighbour node based on ant colony system transition probability

        Args:
            current_node (Node): node from which next node should be selected
            path_identifier(String): string which describes path to the current_node
        Returns:
            index of the neighbour which was selected
        """
        probabilities = []
        denominator = 0.0
        for (neighbour, pheromone) in neighbours:
            probabilities.append(pheromone)
            denominator += pheromone
        # Try to perform greedy select - exploitation
        random_variable = random.uniform(0, 1)
        if random_variable <= self.greediness:
            # do greedy select
            max_probability = max(probabilities)
            max_indices = [i for i, j in enumerate(probabilities) if j == max_probability]
            neighbour_index = random.choice(max_indices)
            return neighbours[neighbour_index]
        # Otherwise perform select using roulette wheel - exploration
        probabilities = [x / denominator for x in probabilities]
        probability_sum = sum(probabilities)
        random_treshold = random.uniform(0, probability_sum)
        current_value = 0
        for idx, probability in enumerate(probabilities):
            current_value += probability
            if current_value > random_treshold:
                return neighbours[idx]

    def update_pheromone(self, ant, update_rule):
        current_node = self.graph.input_node
        # Skip input node as it's connected to any previous node
        for node in ant.path[1:]:
            # Use node from path to retrieve it's corresponding node in graph
            neighbour = next((x for x in current_node.neighbours if type(x.node) is type(node)), None)
            # If path was closed using complete_path method, ignore rest of the path
            if neighbour is None:
                break
            # Update pheromone connecting to neighbour
            neighbour.pheromone = update_rule(
                old_value=neighbour.pheromone,
                cost=ant.cost
            )
            # Update attribute pheromone values
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
            # Advance current node
            current_node = neighbour.node

    def local_update(self, old_value, cost):
        return (1 - cfg['pheromone']['decay']) * old_value + (cfg['pheromone']['decay'] * cfg['pheromone']['start'])

    def global_update(self, old_value, cost):
        # Calculate solution cost based on metrics
        added_pheromone = (1 / (cost * 10)) if cfg['metrics'] == 'loss' else cost
        return (1 - cfg['pheromone']['evaporation']) * old_value + (cfg['pheromone']['evaporation'] * added_pheromone)


class Ant:
    def __init__(self, path=[]):
        self.path = path
        self.loss = math.inf
        self.accuracy = 0.0
        self.path_description = None
        self.path_hash = None

    @property
    def cost(self):
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

    def describe_path(self):
        described_nodes = []
        for node in self.path:
            attributes = ', '.join([a.name + ":" + str(getattr(node, a.name)) for a in node.attributes])
            described_nodes.append(node.name + "(" + attributes + ")")
        path_description = ' -> '.join([described_node for described_node in described_nodes])
        return path_description

    def evaluate(self, backend, storage):
        # Update path description
        self.path_description = self.describe_path()
        self.path_hash = hashlib.sha3_256(self.path_description.encode('utf-8')).hexdigest()
        # Check if model already exists if yes, then just re-use it
        existing_model = storage.load_model(backend, self.path_hash)
        if existing_model is None:
            # Generate model
            new_model = backend.generate_model(self.path)
        else:
            # Re-use model
            new_model = existing_model
        # Train model
        new_model = backend.train_model(new_model)
        # Evaluate model
        self.loss, self.accuracy = backend.evaluate_model(new_model)
        # Save model
        storage.save_model(backend, new_model, self.path_hash)