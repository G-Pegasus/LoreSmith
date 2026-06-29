package com.ainovel.platform.application;

import com.ainovel.platform.domain.model.StoryRecord;
import com.ainovel.platform.infrastructure.repository.StoryRunRepository;
import com.ainovel.platform.interfaces.dto.CreateStoryRequest;
import com.ainovel.platform.interfaces.dto.CreateStoryResponse;
import com.ainovel.platform.interfaces.dto.DeleteStoryResponse;
import com.ainovel.platform.interfaces.dto.StoryListResponse;
import com.ainovel.platform.interfaces.dto.StoryResponse;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Service
public class StoryApplicationService {
    private final StoryRunRepository repository;

    public StoryApplicationService(StoryRunRepository repository) {
        this.repository = repository;
    }

    public StoryResponse getStory(String storyId) {
        StoryRecord story = repository.findStory(storyId)
                .orElseThrow(() -> new IllegalArgumentException("story not found: " + storyId));
        return new StoryResponse(
                story.storyId(),
                story.title(),
                story.premise(),
                story.genre(),
                story.style(),
                story.characters(),
                story.wordCount(),
                story.latestRunId(),
                story.createdAt().toString()
        );
    }

    public StoryListResponse listStories() {
        List<StoryResponse> items = repository.listStories().stream()
                .sorted(Comparator.comparing(StoryRecord::createdAt))
                .map(story -> new StoryResponse(
                        story.storyId(),
                        story.title(),
                        story.premise(),
                        story.genre(),
                        story.style(),
                        story.characters(),
                        story.wordCount(),
                        story.latestRunId(),
                        story.createdAt().toString()
                ))
                .toList();
        return new StoryListResponse(items);
    }

    public CreateStoryResponse createStory(CreateStoryRequest request) {
        StoryRecord story = new StoryRecord(
                request.storyId(),
                request.title(),
                request.premise(),
                request.genre() == null ? "" : request.genre().trim(),
                "",
                request.characters() == null ? List.of() : request.characters().stream()
                        .filter(item -> item != null && item.name() != null && !item.name().isBlank())
                        .map(item -> Map.<String, Object>of(
                                "name", item.name().trim(),
                                "role", item.role() == null ? "" : item.role().trim(),
                                "description", item.description() == null ? "" : item.description().trim()
                        ))
                        .toList(),
                normalizeWordCount(request),
                Instant.now(),
                request.runId()
        );
        repository.saveStory(story);

        return new CreateStoryResponse(request.storyId(), request.runId(), "created", "idle");
    }

    public DeleteStoryResponse deleteStory(String storyId) {
        repository.findStory(storyId)
                .orElseThrow(() -> new IllegalArgumentException("story not found: " + storyId));
        repository.deleteRunsByStoryId(storyId);
        boolean deleted = repository.deleteStoryById(storyId);
        return new DeleteStoryResponse(storyId, deleted);
    }

    private Map<String, Object> normalizeWordCount(CreateStoryRequest request) {
        int minWords = request.wordCount() == null || request.wordCount().minWords() == null ? 2000 : Math.max(2000, request.wordCount().minWords());
        int targetWords = request.wordCount() == null || request.wordCount().targetWords() == null ? 2500 : Math.max(minWords, request.wordCount().targetWords());
        Map<String, Object> wordCount = new LinkedHashMap<>();
        wordCount.put("minWords", minWords);
        wordCount.put("targetWords", targetWords);
        return wordCount;
    }

}
