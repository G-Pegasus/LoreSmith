package com.ainovel.platform.interfaces.dto;

public record StoryWordCountRequest(
        Integer minWords,
        Integer targetWords
) {}
